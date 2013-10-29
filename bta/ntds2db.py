#! /usr/bin/env python

# This file is part of the BTA toolset
# (c) EADS CERT and EADS Innovation Works


import os,sys

import libesedb

import bta.tools.progressbar
import bta.tools.RPNedit
import bta.backend.mongo
import bta.postprocessing
import bta.dblog

import logging
log = logging.getLogger("bta.ntds2db")

def win2epoch(x):
    return x-11644473600

def dbsanecolname(x):
    return x.replace("-","_")


class ESEColumn(object):
    def __init__(self, name, attname, type_, index=False):
        self.name = name
        self.attname = attname
        self.type = type_
        self.index = index
    def to_json(self):
        return dict((k,v) for (k,v) in self.__dict__.iteritems() if not k.startswith("_"))

class ESETable(object):
    _columns_ = []  # db col name # dt name # db type # index?
    _tablename_ = None
    _indexes_ = []

    def __init__(self, options):
        self.options = options
        self.backend = options.backend
        self.attname2col =  { col.attname:col for col in self._columns_ }
        self.esedb = options.esedb
        self.esetable = options.esedb[self._tablename_]

    def identify_columns(self):
        columns = []
        for c in self.esetable.columns:
            if c.name in self.attname2col:
                esecol = self.attname2col[c.name] 
            else:
                esecol = ESEColumn(dbsanecolname(c.name), c.name, "UnknownType")
            columns.append(esecol)
        return columns

    def parse_file(self, dbtable):
        total = self.esetable.number_of_records
        log.info("Parsing ESE table. %i records." % total)
        pbar  = self.options.progress_bar(total, desc="Importing [%s.%s]" % (dbtable.db.name,self._tablename_), 
                                          step=100, obj="rec")
        next(pbar)
        try:
            for rec in self.esetable.iter_records():
                dbtable.insert_fields([val.value for val in rec])
                next(pbar)
        except KeyboardInterrupt:
            log.info("Interrupted by user")
            raise
        else:
            log.info("done.")

    def create(self):
        log.info("### Starting importation of %s ###" % self._tablename_)
        self.options.dblog.update_entry("Start of importation of [%s]" % self._tablename_)
        columns = self.identify_columns()

        metatable = self.backend.open_table(self._tablename_+"_meta")

        table = self.backend.open_table(self._tablename_)
        table.create_fields(columns)
        for idx in self._indexes_:
            table.create_index(idx)
        self.parse_file(table)

        self.options.dblog.update_entry("End of importation of [%s]. %i records." % (self._tablename_, table.count()))
        self.options.dblog.update_entry("Start of creation of metatable for [%s]" % self._tablename_)

        log.info("Creating metatable")
        for col in columns:
            metatable.insert(col.to_json())
        self.options.dblog.update_entry("End of creation of metatable for [%s]" % self._tablename_)
        log.info("Importation of %s is done." % self._tablename_)




class SDTable(ESETable):
    _tablename_ = "sd_table"
    _columns_ = [
        ESEColumn("sd_id", "sd_id", "Int", True),
        ESEColumn("sd_hash", "sd_hash", "Binary", True),
        ESEColumn("sd_refcount", "sd_refcount", "Int", True),
        ESEColumn("sd_value", "sd_value", "SecurityDescriptor", False)
        ]

class LinkTable(ESETable):
    _tablename_ = "link_table"
    _columns_ = [
        ESEColumn("link_DNT", "link_DNT", "Int", True),
        ESEColumn("backlink_DNT", "backlink_DNT", "Int", True),
        ESEColumn("link_base", "link_base", "Int", True),
        ESEColumn("link_deactivetime", "link_deactivetime", "Timestamp", True),
        ESEColumn("link_deltime", "link_deltime", "Timestamp", True),
        ESEColumn("link_usnchanged", "link_usnchanged", "Int", True),
        ESEColumn("link_ncdnt", "link_ncdnt", "Int", True),
        ESEColumn("link_metadata", "link_metadata", "Binary", True),
        ESEColumn("link_data", "link_data", "Binary", True),
        ESEColumn("link_ndesc", "link_ndesc", "Text", True),
        ]

class Datatable(ESETable):
    _tablename_ = "datatable"
    _columns_ = [
        ESEColumn("DNT_col", "DNT_col", "Int", True),
        ESEColumn("PDNT_col", "PDNT_col", "Int", True),
        ESEColumn("time_col", "time_col", "Timestamp", True),
        ESEColumn("objectSid", "ATTr589970", "SID", True),
        ESEColumn("objectGUID", "ATTk589826", "GUID", True),
        ESEColumn("schemaIDGUID", "ATTk589972", "GUID", True),
        ESEColumn("Ancestors_col", "Ancestors_col", "Ancestors", True),
        ESEColumn("userAccountControl", "ATTj589832", "UserAccountControl", False),
        ]
    _indexes_ = [ "rightsGuid" ]

    ATTRIBUTE_ID = 131102      # ATTc131102
    ATTRIBUTE_SYNTAX = 131104  # ATTc131104
    LDAP_DISPLAY_NAME = 131532 # ATTm131532
    MSDS_INTID = 591540        # ATTj591540

    attsyntax2type = {
        0x80001: "DN",                   # 2.5.5.1
        0x80002: "OID",                  # 2.5.5.2
        0x80003: "CaseExactString",      # 2.5.5.3
        0x80004: "CaseIgnoreString",     # 2.5.5.4
        0x80005: "IA5String",            # 2.5.5.5
        0x80006: "NumericString",        # 2.5.5.6
        0x80007: "DNWithBinary",         # 2.5.5.7
        0x80008: "Boolean",              # 2.5.5.8
        0x80009: "Enumeration",          # 2.5.5.9
        0x8000a: "OctetString",          # 2.5.5.10
        0x8000b: "GeneralizedTime",      # 2.5.5.11
        0x8000c: "DirectoryString",      # 2.5.5.12    # separated by ';' when not single valued
        0x8000d: "PresentationAddress",  # 2.5.5.13
        0x8000e: "DNWithString",         # 2.5.5.14
        0x8000f: "NTSecurityDescriptor", # 2.5.5.15
        0x80010: "Integer8",             # 2.5.5.16
        0x80011: "Sid",                  # 2.5.5.17
        }

    type2type = {
        "DN": ("Text",False),
        "OID": ("Text",False),
        "CaseExactString" : ("Text",False),
        "GeneralizedTime" : ("Timestamp",False),
        "Integer8": ("Int",False),
        "NTSecurityDescriptor" : ("NTSecDesc",True),
        }
    
    def syntax_to_type(self, s):
        return self.type2type.get(self.attsyntax2type.get(s), ("UnknownType",False))


    def identify_columns(self):
        log.info("Resolving column names")
        att2ldn = {}
        att2asy = {}
        cols = { int(c.name[4:]):c for c in self.esetable if c.name.startswith("ATT")}
        nbcols = len(cols)
        log.info("%i columns to be identified, out of %i" % (nbcols,len(self.esetable.columns)))

        try:
            lcols = [cols[self.ATTRIBUTE_ID], cols[self.MSDS_INTID], 
                     cols[self.ATTRIBUTE_SYNTAX], cols[self.LDAP_DISPLAY_NAME]]
        except IndexError:
            raise Exception("Missing ldap display name or attribute id or syntax column in datatable")

        pbar = self.options.progress_bar(self.esetable.number_of_records, desc="Scanning for column names", step=100, obj="recs")
        next(pbar)
        for rec in self.esetable.iter_records(columns=lcols):
            next(pbar)
            aid,amsds,asy,ldn = list(rec)
            if not ldn.value:
                continue
            if aid.value is None and amsds.value is None or not ldn.value:
                continue
            cc = cols.pop(aid.value, None)
            if not cc:
                cc = cols.pop(amsds.value, None)
            if cc:
                att2ldn[cc.name] = ldn.value
                att2asy[cc.name] = asy.value
            if not cols:
                log.info("All columns found! Ending scan early!")
                break

        log.info("Resolved %i / %i columns." % (len(att2ldn),nbcols))
        columns = []
        for c in self.esetable.columns:
            if c.name in self.attname2col:
                esecol = self.attname2col[c.name] 
            else:
                synt,idx = self.syntax_to_type(att2asy.get(c.name))
                esecol = ESEColumn(
                    dbsanecolname(att2ldn.get(c.name, c.name)),
                    c.name, synt, idx)
            columns.append(esecol)
        return columns


def import_file((options, fname, connection)):

    backend_class = bta.backend.Backend.get_backend(options.backend_class)
    options.backend = backend_class(options, connection)

    try:
        with bta.dblog.DBLogEntry.dblog_context(options.backend) as options.dblog:
            if not options.only_post_proc:
                log.info("Opening [%s]" % fname)
                options.esedb = libesedb.ESEDB(fname)
                log.info("Opening done.")
            
                options.dblog.update_entry("Opened ESEDB file [%s]" % fname)
                
                if options.only.lower() in ["", "sdtable", "sd_table", "sd"]:
                    sd = SDTable(options)
                    sd.create()
                if options.only.lower() in ["", "linktable", "link_table", "link"]:
                    lt = LinkTable(options)
                    lt.create()
                if options.only.lower() in ["", "datatable", "data"]:
                    dt = Datatable(options)
                    dt.create()
                
                options.backend.commit()
        
            if not options.no_post_proc:
                options.dblog.update_entry("Starting post-processing")
                pp = bta.postprocessing.PostProcessing(options)
                pp.post_process_all()
    except KeyboardInterrupt:
        log.info("Interrupted by user (Ctrl-C)")



def main():
    import optparse
    parser = optparse.OptionParser("Usage: %prog {-C <dbcnx>|--C-list <dbcnxlist>|--C-from <dbcnxfmt> <rpnprog>} [options] path/to/ntds.dit [path/to/other.ntds.dit [...]]")
    
    parser.add_option("-C", dest="connections", default=[], action="append",
                      help="Backend connection string. Ex: 'dbname=test user=john' for PostgreSQL or '[ip]:[port]:dbname' for mongo)", metavar="CNX")
    parser.add_option("--C-list", dest="connection_list",
                      help="Comma seaparated list of backend connection strings, one for each file to import")
    parser.add_option("--C-from-filename", nargs=2, dest="connection_from_filename",
                      help="RPN program to infer connection name from filename. "
                      + 'Ex: -C-from "::%s" "basename rmext - '' replace upper"', metavar="CNXFMT RPNPROG")

    parser.add_option("-B", dest="backend_class", default="mongo",
                      help="database backend (amongst: %s)" % (", ".join(bta.backend.Backend.backends.keys())))

    
    parser.add_option("--only", dest="only", default="",
                      help="Restrict import to TABLENAME", metavar="TABLENAME")
    parser.add_option("--append", dest="append", action="store_true",
                      help="Append ESE tables to existing data in db")
    parser.add_option("--overwrite", dest="overwrite", action="store_true",
                      help="Delete tables that already exist in db")
    parser.add_option("--no-post-processing", dest="no_post_proc", action="store_true",
                      help="Don't post-process imported data")
    parser.add_option("--only-post-processing", dest="only_post_proc", action="store_true",
                      help="Do not import any tables, only post-process data")

    parser.add_option("--multi", dest="multi", action="store_true",
                      help="Spawn many workers")
    parser.add_option("--proc-num", dest="procnb", default=None,
                      help="Number of workers. Default: as much as processors")
    parser.add_option("-y", dest="yes", action="store_true",
                      help="Do not ask for validations")
    parser.add_option("-v", dest="verbose", action="count", default=3,
                      help="be more verbose (can be used many times)")
    parser.add_option("-q", dest="quiet", action="count", default=0,
                      help="be more quiet (can be used many times)")

    options, args = parser.parse_args()
    
    if not args:
        parser.error("Missing paths to ntds.dit files to import")

    if (int(bool(options.connection_list))+
        int(bool(options.connections))+
        int(bool(options.connection_from_filename))) > 1:
        parser.error("-C, --Clist and --Cfromfilename are incompatible")

    options.verbosity = max(1,50+10*(options.quiet-options.verbose))
    logging.basicConfig(format="%(levelname)-5s: %(message)s", level=options.verbosity)

    if options.connection_list:
        options.connections = options.connection_list.split(",")
    if options.connection_from_filename:
        cnxfmt,dbprog = options.connection_from_filename
        ed = bta.tools.RPNedit.RPNFilenameEditor(dbprog)
        options.connections = [cnxfmt % ed(fname) for fname in args]

    if len(args) != len(options.connections):
        parser.error("There are %i ntds.dit files to import while there are only %i destinations (-C)" %
                     (len(args), len(options.connections)))
    

    for fname,cnx in zip(args, options.connections):
        log.info("Going to import %-15s <- %s" % (cnx,fname))
    if not options.yes and len(options.connections) > 1:
        while True:
            print >>sys.stderr,"Can I carry on ? (y/n) ",
            r = raw_input().lower().strip()
            if r == "y":
                break
            elif r == "n":
                log.error("Interrupted by user.")
                raise SystemExit

    jobs = [ (options, fname, cnx) 
             for fname,cnx in zip(args, options.connections) ]

    if options.multi:
        import multiprocessing
        manager = multiprocessing.Manager()
        options.progress_bar = bta.tools.progressbar.StderrMultiProgressBarMothership(manager)
        pool = multiprocessing.Pool(options.procnb)
        pool.map(import_file, jobs)
    else:
        options.progress_bar = bta.tools.progressbar.stderr_progress_bar
        map(import_file, jobs)


if __name__ == "__main__":
    main()
