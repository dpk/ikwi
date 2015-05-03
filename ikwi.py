import mimetypes
import os
import os.path
from urllib.parse import urlparse, urljoin
import yaml
import random

import bcrypt
from jinja2 import Environment
import pypandoc

# Save PEP 3122!
if "." in __name__:
    from .storage import Storage, Signature
    from .util import url_to_title, url_to_filename, title_to_filename, sanitize_html, StorageTemplateLoader
    from .www import Application, Request, Response, JSONResponse
    from .search import LinksDatabase, SearchDatabase
else:
    from storage import Storage, Signature
    from util import url_to_title, url_to_filename, title_to_filename, sanitize_html, StorageTemplateLoader
    from www import Application, Request, Response, JSONResponse
    from search import LinksDatabase, SearchDatabase


class Ikwi(Application):
    image_extensions = ['.jpg', '.png', '.svg', '.gif']
    version = '0.1'
    
    def __init__(self, repo_path):
        self.storage = Storage(repo_path)
        
        self.base_url = ''
        self.base_path = ''
        self.config = {}
        self.config_revision = None
        self.jinja_env = Environment(
            loader=StorageTemplateLoader(self.storage),
            autoescape=True
        )
        self.jinja_env.globals = {
            'site_url': self.site_url
        }
        
        self.links = LinksDatabase(self)
        self.search = SearchDatabase(self)

    def before_request(self, request):
        self.latest = self.storage.latest()
        if self.latest.revision != self.config_revision:
            self.config = yaml.load(self.latest.get('site.yaml').decode('utf-8'))
            if 'base_url' in self.config:
                self.base_url = self.config['base_url']
                self.base_path = urlparse(self.base_url).path.rstrip('/')
            else:
                self.base_url = '/'
        request.path = request.path[len(self.base_path):]

    def site_url(self, path=''):
        return urljoin(self.base_url, path)

    def is_internal_link(self, path):
        if path.startswith(self.base_url):
            internal_path = path[len(self.base_url):].strip('/')
        elif path.startswith('/' + self.base_path):
            internal_path = path[len(self.base_path)+1:].strip('/')
        elif not path.startswith('/'):
            internal_path = path
        else:
            return False
        
        parts = internal_path.split('/')
        if len(parts) == 0: return True # link to homepage
        if parts[0] in {'files', 'images', 'site'}:
            return False
        else:
            return True

    def render_template(self, template_name, **context):
        t = self.jinja_env.get_template(template_name)
        vars = self.config.copy()
        vars.update(context)
        
        return Response(t.render(vars), mimetype='text/html')

    def dispatch_request(self, request):
        base, *path = request.path.strip('/').split('/')
        
        if base == 'files':
            self.require_method(request, ['GET'])
            return self.serve_file(path, request)
        elif base == 'images':
            self.require_method(request, ['GET'])
            if len(path) == 0: return self.not_found()
            
            if request.query_verb == 'old' and 'rev' in request.args:
                old = self.storage.at_revision(request.args['rev'])
                return self.serve_image(path[0], old, request)
            else:
                return self.serve_image(path[0], self.latest, request)
        elif base == 'site':
            self.require_method(request, ['GET'])
            if path == ['edit.js']:
                js_dir = os.path.join(os.path.dirname(__file__), 'js')
                js_files = ['squire.js', 'jquery.js', 'underscore.js', 'editor.js']
                def js_gen():
                    for js_filename in js_files:
                        with open(os.path.join(js_dir, js_filename), 'rb') as file:
                            yield from file
                            yield b'\n'
            
                response = Response(js_gen(), mimetype='application/javascript')
                #response.set_etag(Ikwi.version)
                #response.make_conditional(request)
                return response
            if path == ['search']:
                results = self.search.search(request.args['q'])
                return JSONResponse({'query': request.args['q'], 'results': results})
            else:
                return self.not_found()
        else:
            self.require_method(request, ['GET', 'POST'])
            if len(path) > 0: return self.not_found()
            
            url_page_name = (base or 'Homepage')
            if request.method == 'GET':
                if request.query_verb == 'old':
                    return self.show_page(url_page_name, self.storage.at_revision(request.args['rev']))
                elif request.query_verb == 'edit':
                    self.must_login(request)
                    return self.edit_page(url_page_name)
                elif request.query_verb == 'inlinks':
                    return self.show_inlinks(url_page_name)
                elif request.query_verb in {None, 'no-redirect'}:
                    return self.show_page(url_page_name, self.latest)
                else:
                    return self.not_found()
            elif request.method == 'POST':
                self.must_login(request)
                return self.save_page(url_page_name, request)

    def to_html(self, source):
        return pypandoc.convert(source, 'html', format=self.config['page_format'])
    def to_source(self, html):
        return pypandoc.convert(html, self.config['page_format'], format='html')

    def get_page(self, url_page_name, revision):
        pages = revision.dir('pages')
        filename = url_to_filename(url_page_name)
        if filename in pages:
            return pages.get(filename)
        else:
            return None

    def header_image(self, page_filename, revision):
        if revision.revision != self.latest.revision:
            old_string = '?old&rev=%s' % revision.revision
        else:
            old_string = ''
        
        images = revision.dir('images')
        for extension in Ikwi.image_extensions:
            image_filename = page_filename + extension
            if image_filename in images:
                return self.site_url('images/' + image_filename + old_string)

    def show_page(self, url_page_name, revision):
        page_title = url_to_title(url_page_name)
        page_source = self.get_page(url_page_name, revision)
        
        if not page_source:
            return self.not_found(creatable=True)
        
        page_content = self.to_html(page_source)
        header_image = self.header_image(url_to_filename(url_page_name), revision)
        
        response = self.render_template('page.html', page_title=page_title, page_content=page_content, header_image=header_image)
        # todo: make response cacheable
        return response
    
    def edit_page(self, url_page_name):
        page_title = url_to_title(url_page_name)
        page_source = self.get_page(url_page_name, self.latest)
        
        if not page_source:
            page_content = '<p></p>'
        else:
            page_content = self.to_html(page_source)
        
        header_image = self.header_image(url_to_filename(url_page_name), self.latest)
        
        return self.render_template('edit.html', page_title=page_title, page_content=page_content, header_image=header_image, revision_id=self.latest.revision)
    
    def save_page(self, filename, request):
        title = request.form['title']
        html = sanitize_html(request.form['content'])
        filename = title_to_filename(title)
        
        cursor = self.storage.cursor(request.form['revision'])
        cursor.add('pages/' + filename, self.to_source(html).encode('utf-8'))
        
        if 'headerimage' in request.files:
            header_image = request.files['headerimage'].read()
            extension = mimetypes.guess_extension(request.files['headerimage'].mimetype)
            if extension.startswith('.jpe'): extension = '.jpg' # wtf Python?!
            
            if extension in Ikwi.image_extensions:
                image_filename = filename + extension
                for other_extension in Ikwi.image_extensions:
                    cursor.delete('images/' + filename + other_extension)
                
                cursor.add('images/' + image_filename, header_image)
            
        cursor.save('%s: %s' % (title, request.form.get('change_message', '')), Signature(self.config['editors'][request.authorization.username]['name'], self.config['editors'][request.authorization.username]['email']))
        status = cursor.update('HEAD')
        
        if status.conflict:
            return JSONResponse({
                'status': 'conflict',
                'source': status.source_revision,
                'target': status.target_revision,
            }, 409)
        
        return JSONResponse({'status': 'ok', 'revision': status.revision})

    def show_inlinks(self, url_page_name):
        page_title = url_to_title(url_page_name)
        filename = url_to_filename(url_page_name)
        inlinks = self.links.inlinks(filename)
        return self.render_template('inlinks.html', inlinks=inlinks, page_title=page_title, page_url=url_page_name)

    def serve_file(self, path, request):
        path = path[0]
        dir = self.latest.dir('files')
        if path not in dir:
            return self.not_found()
        
        type, encoding = mimetypes.guess_type(path)
        
        # prevent the blob from being decoded unless actually needed
        def yield_get(): yield dir.get(path)
        response = Response(yield_get(), mimetype=type, direct_passthrough=True)
        response.set_etag(dir.get_id(path))
        response.make_conditional(request)
        return response

    def serve_image(self, path, revision, request):
        path = url_to_filename(path)
        dir = self.latest.dir('images')
        if path not in dir:
            return self.not_found()
        type, encoding = mimetypes.guess_type(path)
        
        # prevent the blob from being decoded unless actually needed
        def yield_get(): yield dir.get(path)
        response = Response(yield_get(), mimetype=type, direct_passthrough=True)
        response.set_etag(dir.get_id(path))
        response.make_conditional(request)
        return response

    def must_login(self, request):
        if not request.authorization:
            raise PermissionError
        
        username = request.authorization.username
        try_password = request.authorization.password.encode('utf-8')
        if username not in self.config['editors']:
            raise PermissionError
        
        real_password = self.config['editors'][username]['password'].encode('utf-8')
        if bcrypt.hashpw(try_password, real_password) != real_password:
            raise PermissionError
    
    def unauthorized(self):
        response = self.render_template('unauthorized.html')
        response.headers.extend({
            'WWW-Authenticate': 'Basic realm="%s"' % self.config['site_title']
        })
        return Response(
            response.response,
            401,
            response.headers
        )
    
    def not_found(self, creatable=False):
        response = self.render_template('not_found.html', creatable=creatable)
        return Response(
            response.response,
            404,
            response.headers
        )
