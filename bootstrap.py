'''
Created on 25.09.2014

@author: d021770
'''

import appcache
import time
import sys,os
import xmake
import urllib
import subprocess
import shutil
import imp
import re
import traceback
import log
import options
from tarfile import TarFile

from os.path import join, getctime, getmtime, isdir, isfile, basename, expanduser
from os import listdir, remove, environ
from utils import read_first_line, get_first_line, get_installation_dir, get_technical_xmake_version, touch_file, is_existing_file
from utils import rmtree, cat, is_existing_directory, flush, contains
from config import BuildConfig
from phases.prelude import setup_config, determine_version, create_gendir
from xmake_exceptions import XmakeException
from ExternalTools import tool_package_url,tool_retrieve_url

import xml.etree.ElementTree as ET

from const import XMAKE_NEXUS

XMAKE_VERSION   = 'XMAKE_VERSION'
XMAKE_CHECK_TIME            = 12*60*60
XMAKE_EXPIRE_TIME           = 24*60*60
XMAKE_PKG_NEXUS = XMAKE_NEXUS
XMAKE_PKG_REPO  = 'build.snapshots.xmake'
XMAKE_PKG_GID  = 'com.sap.prd.xmake'
XMAKE_PKG_AID  = 'xmake'
XMAKE_PKG_SUF  = 'tar.gz'

test_mode=False

def versionlist_url():
    url='/'.join([XMAKE_PKG_NEXUS,'nexus/content/groups',XMAKE_PKG_REPO,XMAKE_PKG_GID.replace('.', '/'),XMAKE_PKG_AID,'maven-metadata.xml'])
    return url

def package_url(v):
    return tool_package_url((XMAKE_PKG_GID,XMAKE_PKG_AID,XMAKE_PKG_SUF,'',v),XMAKE_PKG_REPO,XMAKE_PKG_NEXUS)

def get_version_list():
    f=urllib.urlopen(versionlist_url())
    root=ET.parse(f)
    return [ x.text for x in root.findall("./versioning/versions/version")]

def find_latest(p):
    found=p
    try:
        p.index('*')
        p=p.replace('*','(.*)')
        m=-1
        for v in get_version_list():
            mo=re.compile(p).match(v)
            if mo!=None:
                try:
                    c=int(mo.group(1))
                    if (c>m):
                        found=v
                        m=c
                except ValueError:
                    pass
    except ValueError:
        pass
    return found
   
def update_snapshot(versions,v):
    a=versions._retriever(v)
    x=TarFile.open(a,'r').extractfile("sourceversion.txt")
    sv=read_first_line(x,'cannot read sourcerversion.txt from '+a)
    log.info( "latest version of "+v+' is '+sv)
    
    def retrieve(aid):
        return a

    x=versions.get((v,sv),retrieve)
    d=versions.path(v)
    if isdir(d): touch_file(d)
    return x

xmake_loaded=None

def get_xmake_version(v, build_cfg):
    def finalize(aoid,d):
        touch_file(join(d,'.loaded'))
        
    def retrieve(aid):
        url=package_url(aid)
        if test_mode:
            return join(build_cfg.gen_dir(),"xmake.tar.gz")
        return tool_retrieve_url(url,aid,XMAKE_PKG_REPO)
    
    if environ.has_key('XMAKE_VERSION_INSTALLATION_ROOT'):
        version_root=environ['XMAKE_VERSION_INSTALLATION_ROOT']
        if not is_existing_directory(version_root):
            log.error("env var 'XMAKE_VERSION_INSTALLATION_ROOT' was set, but does not point to an existing directory. Either unset or change it")
            raise XmakeException("encountered invalid value of env var 'XMAKE_TOOL_INSTALLATION_ROOT'")
    else:
        version_root=join(expanduser("~"),'.xmake','versions')
        
    #xmake_inst_dir = get_installation_dir()
    #version_root=join(xmake_inst_dir,"versions")
    
    versions=appcache.AppCache("xmake",join(version_root),retrieve,finalize)
    
    if (v.endswith("-SNAPSHOT")):
        p=versions.path(v)
        latest=get_latest(p)
        if latest==None:
            log.info('no snapshot found for '+v+' -> load new version')
            return update_snapshot(versions,v)
        else:
            cleanup(p)
            try:
                if build_cfg.do_import():
                    log.info('check for newer snapshot for xmake version '+v)
                    return update_snapshot(versions,v)
                else:
                    c=time.time()
                    t=getmtime(p)
                    if t+XMAKE_CHECK_TIME<c:
                        log.info('check time exceeded for '+v+' -> check for newer snapshot')
                        return update_snapshot(versions,v)
            except XmakeException as xme:
                log.warning('update of xmake version failed: '+ xme.msg)
                log.warning('reusing actually available snapshot')
        return latest
    else:
        return versions.get(v)
    
def cleanup(d):
    expired=[]
    c=time.time()-XMAKE_EXPIRE_TIME

    def clean(skip,cand):
        if skip[0]<c and skip[1]!=None:
            expired.append(skip[1])
       
    get_latest(d,clean) 
    
    if len(expired)>0:
        log.info('cleanup expired snapshot versions '+str([ basename(x) for x in expired]))
        for d in expired:
            try:
                rmtree(d)
            except OSError:
                log.info('  failed to delete '+d)
                    
def get_latest(d,h=lambda x,y:True):
    found=[0,None]
    if isdir(d):
        for f in listdir(d):
            p=join(d,f)
            if isdir(p):
                cur=[getctime(p),p]
                if cur[0]>found[0]:
                    skip=found
                    found=cur
                else:
                    skip=cur
                h(skip,found)
    return found[1]

def remove_arg(a,n, args):
    for i in range(len(args)):
        if args[i].startswith('--') or n>0:
            if args[i].startswith(a):
                if args[i]==a:
                    args=args[:i]+args[i+n+1:]
                else:
                    args=args[:i]+args[i+1:]
                break
        else: # potential accumulated flag arg
            if args[i].startswith('-') and len(a)==2:
                if args[i] == a:
                    args=args[:i]+args[i+n+1:]
                    break
                else:
                    ix=args[i].find(a[1])
                    if (ix>0):
                        args[i]=args[i][:ix]+args[i][ix+1:]
                        break
    return args
                
def prepare_args(path, args):
    log.info("  cleanup command line for selected xmake version")
    args=remove_arg('-X',1,args)
    args=remove_arg('--xmake-version',1,args)
    args=remove_arg('--default-xmake-version',1,args)

    p=join(path,'xmake','options.py')
    targetopts=None
    if is_existing_file(p):
        log.info("  loading options for selected xmake version")
        mod = imp.load_source('targetoptions', p)
        targetopts=mod.cli_parser()
    else:
        log.info('  falling back to default options for older xmake version')
        targetopts=options.base_09_options();
    
    if targetopts is not None:
        def handle_option(o,args):
                #log.info("    opt: "+o)
                if o != '-V' and not o.startswith('--variant-') and not targetopts.has_option(o):
                    index=contains(o,'=')
                    if index>=0:
                        k=o[:index]
                    else:
                        k=o
                    #log.info("found unsupported option "+k)
                    nargs=curopts.get_option(k).nargs
                    log.warning("given option '"+k+"' with "+str(nargs)+" arg(s) is not supported by selected xmake version -> option omitted")
                    if k!=o:
                        nargs=0
                    args=remove_arg(o,nargs,args)
                return args
                
        curopts=options.cli_parser()
        for a in [ x for x in args] :
            if a.startswith('-'):
                if a == '--':
                    break
                #log.info("  arg: "+a)
                if a.startswith('--'):
                    args=handle_option(a,args)
                else:
                    for o in a[1:]:
                        args=handle_option('-'+o,args)
                    
    log.info("effective args: "+str(args))               
    return args
    
        
xmake_status='installed'
build_cfg=None

def main(argv=sys.argv):
    try:
        bootstrap(argv)
    except SystemExit:
        raise
    except BaseException as ex:
        if log.get_last_log_category() != log.ERR:
            log.error(str(ex), log.INFRA)
        if build_cfg is None or build_cfg.is_tool_debug():
            print "---------------"
            traceback.print_exc()
            print "---------------"
        sys.exit(1)
        
def prepare_bootstrap():
    global XMAKE_PKG_NEXUS
    if os.environ.has_key("XMAKE_NEXUS_HOST"):
        XMAKE_PKG_NEXUS=os.environ.get("XMAKE_NEXUS_HOST")
        
def handle_bootstrapper(xmake_inst_dir,argv):
    f=join(xmake_inst_dir,'BOOTSTRAPPER_VERSION')
    if isfile(f):
        log.info("determining bootstrapper")
        v=get_first_line(f,'cannot read '+f)
        if v!=None:
            v=find_latest(v)
            if v!=None:
                log.info( 'required bootstrapper version is '+v)
                bc=BuildConfig()
                bc._do_import=True
                l=get_xmake_version(v, bc)
                log.info( 'required bootstrapper version found at '+l)
                cmd=[sys.executable, join(l,'xmake','bootstrap.py'),'--bootstrap']
                cmd.extend(argv[1:])
                flush()
                rc=subprocess.call(cmd)
                sys.exit(rc)
      
def bootstrap(argv=sys.argv):
    prepare_bootstrap()
    xmake_inst_dir = get_installation_dir()
    v=get_technical_xmake_version()
    if v != None:
        log.info( 'technical version is '+v)
    log.info( 'python version is '+str(sys.version_info[0])+"."+str(sys.version_info[1])+"."+str(sys.version_info[2]))
    if not (sys.version_info[0]==2 and sys.version_info[1]>=7):
        log.error( "python version 2.7+ required to run xmake")
        sys.exit(2)
    handle_bootstrapper(xmake_inst_dir,argv)
    bootstrap2(argv)
    
def bootstrap2(argv):
    global xmake_status, build_cfg
    prepare_bootstrap()
    xmake_inst_dir = get_installation_dir()
    if len(argv)>1 and argv[1]=='--bootstrap':
        xmake_status='bootstrap'
        sys.argv=argv=argv[0:1]+argv[2:]
    else:
        if isfile(join(xmake_inst_dir,'.loaded')):
            log.warning( 'directly using loaded sub level version of xmake')
            xmake_status='loaded'
        
    if xmake_status=='loaded':
        run(argv)
    else:
        log.info( 'bootstrapping xmake...')
        build_cfg = BuildConfig()
        log.info( 'build runtime is ' + build_cfg.runtime())
        log.info( 'determining required xmake version...')
        (args,config,xmake_file) = setup_config(build_cfg, True)
        create_gendir(build_cfg)
        log.start_logfile(join(build_cfg.genroot_dir(),"boot.log"))
        determine_version(build_cfg, args.version)
                
        if args.use_current_xmake_version:
            log.warning( 'using actually installed version as requested by option --use-current-xmake-version')
            run(argv)
        else:
            vf=join(build_cfg.cfg_dir(),XMAKE_VERSION)
            v=build_cfg.xmake_version()
            if v== None and isfile(vf):
                #print 'INFO: checking',vf
                v=get_first_line(vf,'cannot read '+XMAKE_VERSION)
            if v==None:
                log.warning( 'no xmake version specified (please maintain file '+XMAKE_VERSION+" in project's cfg folder")
                log.info("default version is "+str(args.default_xmake_version))
                if args.default_xmake_version==None:
                    if build_cfg.is_release_build():
                        raise XmakeException('no version specified for xmake for a productive build')
                    else:
                        log.warning( 'using actually installed version')
                        run(argv)
                else:
                    v=args.default_xmake_version
                    log.warning( 'using explicit default version '+v)
            if v==None:
                log.error("do not know any xmake version to use -> exit")
                sys.exit(2)
            else:
                v=find_latest(v)
                log.info( 'required xmake version is '+v)
                if v.endswith("-SNAPSHOT"):
                    if build_cfg.is_release_build():
                        log.error( 'this is a snapshot version, it cannot be used for release builds')
                        raise XmakeException('snapshot version specified for xmake for a productive build')
                    else:
                        log.warning( 'this is a snapshot version, it cannot be used for release builds')
                l=get_xmake_version(v, build_cfg)
                if is_existing_file(xmake_loaded): os.remove(xmake_loaded)
                log.info( 'required xmake version found at '+l)
                if test_mode:
                    cmd=[sys.executable, join(l,'xmake','bootstrap.py'), '--use-current-xmake-version']
                else:
                    cmd=[sys.executable, join(l,'xmake','xmake.py')]
                log.info( 'starting xmake...')
                cmd.extend(prepare_args(l,argv[1:]))
                #print 'INFO: calling '+str(cmd)
                if build_cfg.component_dir()!=None: os.chdir(build_cfg.component_dir())
                flush()
                rc=subprocess.call(cmd)
                sys.exit(rc)
            
    
def run(argv):
    log.stop_logfile()
    print 'INFO: running xmake...'
    if test_mode:
        build_cfg = BuildConfig()
        (args,config,xmake_file) = setup_config(build_cfg, True)
    else:
        xmake.main(argv)
    sys.exit(0)
    
if __name__ == '__main__':
    main(sys.argv)