import os
import os.path
import sqlite3
from urllib.parse import urlparse

import lxml.html.html5parser as html5
import whoosh.fields
import whoosh.index
import whoosh.qparser

if "." in __name__:
    from .database import Database
    from .util import url_to_filename, filename_to_title, filename_to_url
else:
    from database import Database
    from util import url_to_filename, filename_to_title, filename_to_url


ns = {'h':'http://www.w3.org/1999/xhtml'}

class LinksDatabase(Database):
    database_name = 'links.sqlite3'
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.conn = sqlite3.connect(self.path)

    def do_create(self):
        c = self.conn.cursor()
        c.execute("CREATE TABLE links (id INTEGER PRIMARY KEY, source TEXT NOT NULL, target TEXT NOT NULL)")
        c.execute("CREATE INDEX outlinks ON links (source)")
        c.execute("CREATE INDEX inlinks ON links (target)")
        
        c.execute("CREATE TABLE redirects (source TEXT PRIMARY KEY NOT NULL, target TEXT NOT NULL)")
        c.execute("CREATE INDEX aliases ON redirects (target)")
        
        c.execute("CREATE TABLE pageranks (page TEXT PRIMARY KEY NOT NULL, rank REAL NOT NULL)")
        self.conn.commit()
    
    def do_update(self, differences):
        c = self.conn.cursor()
        
        def delete_page(page):
            c.execute('DELETE FROM links INDEXED BY outlinks WHERE source = ?', (page,))
            c.execute('DELETE FROM redirects WHERE source = ?', (page,))
        def index_content(page, content):
            content = content.decode('utf-8')
            if content.startswith('=> '):
                c.execute('INSERT INTO redirects (source, target) VALUES (?, ?)', (page, content[3:].strip()))
                return
            
            src = html5.fragment_fromstring(self.site.to_html(content), create_parent='div')
            links = src.xpath('//h:a[@href]', namespaces=ns)
            page_links = []
            
            for link in links:
                dest = link.attrib['href']
                destinfo = urlparse(dest)
                if self.site.is_internal_link(dest):
                    if dest.startswith('http:') or dest.startswith('https:'):
                        dest_name = url_to_filename(destinfo.path.strip('/'))
                    elif dest.startswith('/' + self.site.base_path):
                        dest_name = url_to_filename(destinfo.path[len(self.site.base_path)+2:])
                    else:
                        dest_name = url_to_filename(destinfo.path.strip('/'))
                    
                    if dest_name == '': dest_name = 'Homepage'
                    page_links.append((page, dest_name))
            
            c.executemany('INSERT INTO links (source, target) VALUES (?, ?)', page_links)
        
        try:
            for page, difference in differences.items():
                op, content = difference
                if op == 'created':
                    index_content(page, content)
                elif op == 'updated':
                    delete_page(page)
                    index_content(page, content)
                elif op == 'deleted':
                    delete_page(page)
        except:
            self.conn.rollback()
            raise
        
        self.conn.commit()

    def inlinks(self, filename):
        self.update()
        c = self.conn.cursor()
        c.execute('SELECT source FROM links WHERE target = ?', (filename,))
        for result in c:
            yield Link(filename_to_url(result[0]), filename_to_title(result[0]))

class Link:
    def __init__(self, url, title):
        self.url = url
        self.title = title

class SearchDatabase(Database):
    database_name = 'search.whoosh'
    schema = whoosh.fields.Schema(
        filename=whoosh.fields.ID(stored=True, unique=True),
        url=whoosh.fields.STORED,
        title=whoosh.fields.TEXT(field_boost=2.0, stored=True),
        content=whoosh.fields.TEXT,
        redirect_to=whoosh.fields.STORED
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        if whoosh.index.exists_in(self.path):
            self.index = whoosh.index.open_dir(self.path)
        else:
            if not os.path.isdir(self.path): os.mkdir(self.path)
            self.index = None
    
    def do_create(self):
        self.index = whoosh.index.create_in(self.path, SearchDatabase.schema)
    
    def do_update(self, differences):
        self.index = self.index.refresh()
        with self.index.writer() as writer:
            for page, difference in differences.items():
                op, content = difference
                
                if content:
                    content = content.decode('utf-8')
                    if content.startswith('=> '):
                        redirect_to = content[3:].strip()
                        doc = {
                            'filename': page,
                            'url': filename_to_url(page),
                            'title': filename_to_title(page),
                            'content': '',
                            'redirect_to': redirect_to
                        }
                    else:
                        src = html5.fragment_fromstring(self.site.to_html(content), create_parent='div')
                        content = ' '.join(src.xpath('//text()'))
                        doc = {
                            'filename': page,
                            'url': filename_to_url(page),
                            'title': filename_to_title(page),
                            'content': content,
                            'redirect_to': None
                        }
                
                if op == 'created':
                    writer.add_document(**doc)
                elif op == 'updated':
                    writer.update_document(**doc)
                elif op == 'deleted':
                    writer.delete_by_term('filename', page)

    def search(self, query):
        self.update()
        self.index = self.index.refresh()
        parser = whoosh.qparser.MultifieldParser(['title', 'content'], SearchDatabase.schema)
        parsed_query = parser.parse(query)
        with self.index.searcher() as searcher:
            results = searcher.search(parsed_query, limit=30)
            return list(dict(result) for result in results)
        
