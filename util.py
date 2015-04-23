import urllib.parse as url
import unicodedata as unicode

import lxml.html.html5parser as html5
import lxml.html
import html5lib
import html


def filename_to_title(filename):
    return url.unquote(filename.replace('_', ' '))
def title_to_filename(title):
    return url.quote(unicode.normalize('NFC', title).replace(' ', '_'))

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
    
