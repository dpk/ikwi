import urllib.parse as urlparse
import unicodedata as unicode

from jinja2 import BaseLoader, TemplateNotFound
import lxml.html.html5parser as html5
import lxml.html
import html5lib
import html


def url_to_title(url):
    return url.replace('_', ' ')
def url_to_filename(url):
    return urlparse.quote(unicode.normalize('NFC', url))
def filename_to_url(filename):
    return urlparse.unquote(filename)
def filename_to_title(filename):
    return urlparse.unquote(filename.replace('_', ' '))
def title_to_filename(title):
    return urlparse.quote(unicode.normalize('NFC', title).replace(' ', '_'))

# clean up after Squire, which is generally pretty clean but still needs some help before we can use feed it to pandoc
def sanitize_html(src):
    h = html5.fragment_fromstring(src, create_parent='div')
    brs = h.xpath('//h:br[count(following-sibling::node()) = 0]', namespaces={'h':'http://www.w3.org/1999/xhtml'})
    for br in brs: br.getparent().remove(br)
    # urgh
    walker = html5lib.getTreeWalker("etree")
    stream = walker(h)
    s = html5lib.serializer.HTMLSerializer()
    return ''.join(s.serialize(stream))[5:-6]

class StorageTemplateLoader(BaseLoader):
    def __init__(self, storage):
        self.storage = storage
    
    def get_source(self, environment, template):
        latest = self.storage.latest()
        templates = latest.dir('templates')
        
        try:
            source = templates.get(template).decode('utf-8')
        except FileNotFoundError:
            raise TemplateNotFound(template)
        
        return source, None, lambda: latest.revision == self.storage.latest().revision
