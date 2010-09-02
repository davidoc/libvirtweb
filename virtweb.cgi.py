#!/usr/bin/env python

TEMPLATE_DIR = 'templates'
#LOCALE = 'en_US.UTF-8'
LOCALE = 'en_IE'

from config import LIBVIRT_URI
from lxml import etree
import sys, os.path, locale, cherrypy, Cheetah.Template, libvirt, binascii
locale.setlocale(locale.LC_ALL, LOCALE)

basepath = os.path.abspath(os.path.dirname(sys.argv[0]))
cherrypy.config.update({
   'tools.staticdir.root': basepath
})
APPCONFIG = {
   '/static': {
      'tools.staticdir.on': True,
      'tools.staticdir.dir': 'static'
   },
}
HTMLESCAPES = [('&', '&amp;'), ('<', '&lt;'), ('>', '&gt;'), ('\'', '&apos;'), ('"', '&quot;')]
NODEINFOELEMENTS = ['arch', 'memory', 'cpus', 'mhz', 'nodes', 'sockets', 'cores', 'threads']
DOMAININFOELEMENTS = ['state', 'maxmemory', 'memory', 'vcpus', 'cputime']
DOMAINSTATES = ['Unknown', 'Running', 'Blocked', 'Paused', 'Shutting down', 'Shut off', 'Crashed']
DOMAINSTATECLASSES = ['att', 'ok', 'att', 'neu', 'neu', 'neu', 'att']


def compare_by (fieldname):
    def compare_two_dicts (a, b):
        return cmp(a[fieldname], b[fieldname])
    return compare_two_dicts 


def htmlescape(text):
   """Escape a string with HTML entities.

   This method is available as $h in templates."""

   for search, replace in HTMLESCAPES:
      text = text.replace(search, replace)
   return text

def prettynumber(num):
   """Format a number in locale-specific format.

   This method is available as $n in templates."""

   return locale.format('%d', num, grouping=True)


templates = {}
def deftemplate(name, mainMethodName='content'):
   """Compile a Cheetah template and add the compiled class to the globals.

   The template should be located in 'templates/name.tmpl'. Other templates
   compiled before will be made available in the template's globals.
   The template will also have the convenience functions $h and $n in
   it's globals."""

   global templates
   path = os.path.join(basepath, TEMPLATE_DIR, '%s.tmpl' % name)
   cherrypy.engine.autoreload.files.add(path)
   klass = Cheetah.Template.Template.compile(
         file=path, mainMethodName=mainMethodName, useCache=False,
         moduleName=name, className=name, moduleGlobals=templates)
   templates[name] = klass
   def tmpl(**kwargs):
      searchList = {'h': htmlescape, 'n': prettynumber}
      searchList.update(kwargs)
      inst = klass(searchList=searchList)
      cherrypy.response.headers['Content-Type'] = inst.content_type
      return inst.respond()
   globals()[name] = tmpl


def maplist(elements, names):
   """Turn a list into a dict, matching indices of elements and names."""

   retval = {}
   for i, name in enumerate(names):
      retval[name] = elements[i]
   return retval


# The templates we use.

# Define layout first, because the other templates use it.
# Layout also hosts the primary 'respond' method, and calls other methods
# on itself, functioning as an abstract base class.
deftemplate('layout', mainMethodName='respond')

# Page templates
deftemplate('nodes_index')

# Ajax templates
deftemplate('ajax_console')


class Node(object):

   def __init__(self, uri=[]):
      self.uri = uri
      self.conn={}
      self.brokenuris=[]
      # FIXME: We should probably have a separate thread hosting the
      # libvirt connection instance, or even a pool of them, because
      # the libvirt API is entirely blocking.

      # The would also allow us to monitor CPU usage and show graphs
      # like virt-manager. And we need to beat virt-manager in awesomeness.
      for myuri in uri:         
         try:
            self.conn[myuri] = libvirt.openReadOnly(myuri)
         except libvirt.libvirtError:
            self.brokenuris.append(myuri)
#            raise ValueError("Could not open the given URI: "+myuri)

   @cherrypy.expose
   def index(self):
      nodes=[]
      # iterate over hosts
      for connkey in self.conn.keys():
         conn=self.conn[connkey]
         # Take the node info, and map the ugly list result from libvirt into a dict
         node = maplist(conn.getInfo(), NODEINFOELEMENTS)
         # Silly libvirt uses a different unit for node memory and domain memory
         node['memory'] = node['memory']

         # Silly libvirt again, defined domains actually does NOT contain all defined domains,
         # but just the non-running ones. We also have no way of getting a list of names
         # for running domains, just the IDs.
         domains1 = [conn.lookupByID(x) for x in conn.listDomainsID()]
         domains2 = [conn.lookupByName(x) for x in conn.listDefinedDomains()]

         domains = {}
         memoryusage = 0   # Total memory usage counter

         for domain in domains1 + domains2:
            # Take domain info, and map ugly list result into dict again
            info = maplist(domain.info(), DOMAININFOELEMENTS)
            # Select a CSS class based on state
            info['stateclass'] = DOMAINSTATECLASSES[info['state']]
            # Prettify state name
            info['state'] = DOMAINSTATES[info['state']]
            info['memory'] = info['memory']/1024
            info['maxmemory'] = info['maxmemory']/1024
            # If we're running, calculate memory usage to the total
            if info['state'] == 'Running' or info['state'] == 'Blocked':
               memoryusage += info['memory']
            domains[domain.name()] = info

         node['memoryusage'] = memoryusage
         # The percentage is both for display and for CSS width
         node['memoryusageperc'] = '%d%%' % int(float(memoryusage) * 100.0 / node['memory'])

         # Create a sorted list of domain names for display order
         domainnames = domains.keys()
         domainnames.sort()
         nodeinfo= {            
            'hostname':       conn.getHostname(),
            'node':           node,
            'domainnames':    domainnames,         'domains':        domains,
            # FIXME: these two are probably just as broken as listDefinedDomains
            'networks':       conn.listDefinedNetworks(),
            'storagePools':   conn.listDefinedStoragePools()
         }
         nodes.append(nodeinfo)

      nodes.sort(compare_by("hostname"))
      
      vars={'nodes':nodes, 'brokenuris':self.brokenuris}
      return nodes_index(**vars)

   @cherrypy.expose
   def ajax_console(self, domainname):
      try:
         for connkey in self.conn.keys():
            myconn=self.conn[connkey]       
            domain = myconn.lookupByName(domainname)
      except libvirt.libvirtError, e:
         raise cherrypy.HTTPError(404, str(e))

      vncport = -1

      # Take the port from the XML description.
      desc = etree.fromstring(domain.XMLDesc(0))
      graphics = desc.find("devices/graphics[@type='vnc']")
      if graphics is not None:
         try:
            vncport = int(graphics.get('port'))
         except ValueError:
            pass
      if vncport == -1:
         return ajax_console(domain=domainname, cookie=None)

      # Build the info dictionary to be passed to rfbproxy.connectVNC
      info = {'vnchost': 'localhost', 'vncport': vncport}
      if self.uri is not None:
         # Split the URI into 'scheme://userhostpart/x'
         x = self.uri
         scheme, x = x.split(':', 1)
         empty, empty, userhostpart, x = x.split('/', 3)

         # Split the scheme into 'virttype+tunnel'
         try:
            virttype, tunnel = scheme.split('+', 1)
         except ValueError:
            virttype = scheme
            tunnel = None

         # Is this a remote connection?
         if userhostpart:
            # See if a username was specified in the URI
            try:
               user, hostpart = userhostpart.split('@', 1)
            except ValueError:
               user = None
               hostpart = userhostpart
            # See if a port was specified in the URI
            try:
               host, port = hostpart.split(':', 1)
               try:
                  port = int(port)
                  if port < 1 or port > 65535:
                     raise ValueError('port out of range')
               except ValueError:
                  port = None
            except ValueError:
               host = hostpart
               port = None

            # If we're tunneling, make sure we fill the right info fields
            if tunnel == 'ssh':
               info['sshhost'] = host
               info['sshport'] = port or 22
               if user:
                  info['sshuser'] = user
            else:
               info['vnchost'] = host

      # Create a cookie, and encrypt it for VNCViewer
      cookie = common.cookies.create(info)
      hexcookie = binascii.hexlify(cookie)

      return ajax_console(domain=domainname, cookie=hexcookie)

import cgitb; cgitb.enable()
mynode=Node(LIBVIRT_URI)
print "Content-Type: text/html"     # HTML is following
print
print mynode.index()
