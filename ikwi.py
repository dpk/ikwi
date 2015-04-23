import mimetypes
import os
import os.path
import yaml

import bcrypt
from jinja2 import Environment, FileSystemLoader
import pypandoc
from werkzeug.wrappers import Request, Response
from werkzeug.serving import run_simple

from IPython import embed
from util import filename_to_title, title_to_filename, sanitize_html


class Ikwi:
    image_extensions = ['.jpg', '.png', '.svg', '.gif']
    
    def __init__(self, site_base):
        self.site_base = os.path.realpath(site_base)
        
        # gitify
        with open(os.path.join(self.site_base, 'site.yaml'), 'r', encoding='utf-8') as config_file:
            self.config = yaml.load(config_file)
        
        self.jinja_env = Environment(
            # gitify
            loader=FileSystemLoader(os.path.join(site_base, 'templates')),
            autoescape=True
        )

    def wsgi_app(self, environ, start_response):
        request = Request(environ)
        try:
            response = self.dispatch_request(request)
        except FileNotFoundError:
            response = self.not_found()
        except PermissionError:
            response = self.unauthorized()
        
        return response(environ, start_response)

    def __call__(self, environ, start_response):
        return self.wsgi_app(environ, start_response)

    def run(self):
        run_simple('127.0.0.1', 3000, self, use_debugger=True, use_reloader=True)


    def render_template(self, template_name, **context):
        t = self.jinja_env.get_template(template_name)
        vars = self.config.copy()
        vars.update(context)
        
        return Response(t.render(vars), mimetype='text/html')

    def dispatch_request(self, request):
        if request.path.startswith('/files/'):
            return self.file_from_directory('files', request.path[7:])
        elif request.path.startswith('/images/'):
            return self.file_from_directory('images', request.path[8:])
        elif request.path == '/site/edit.js':
            js_dir = os.path.join(os.path.dirname(__file__), 'js')
            js_files = ['squire.js', 'jquery.js', 'underscore.js', 'editor.js']
            def js_gen():
                for js_filename in js_files:
                    with open(os.path.join(js_dir, js_filename), 'rb') as file:
                        yield from file
                        yield b'\n'
            
            return Response(js_gen(), mimetype='application/javascript')
        else:
            filename = (request.path[1:] or 'Homepage')
            if request.method == 'GET':
                if request.query_string == b'edit':
                    self.must_login(request)
                    return self.edit_page(filename)
                elif request.query_string == b'':
                    return self.show_page(filename)
            elif request.method == 'POST':
                self.must_login(request)
                return self.save_page(filename, request)

    # gitify
    def get_page(self, filename):
        file_path = self.safe_file_path('pages', title_to_filename(filename))
        with open(file_path, 'r', encoding='utf-8') as file:
            return file.read()

    def to_html(self, source):
        return pypandoc.convert(source, 'html', format=self.config['page_format'])
    def to_source(self, source):
        return pypandoc.convert(source, self.config['page_format'], format='html')

    def show_page(self, filename):
        page_title = filename_to_title(filename)
        page_source = self.get_page(filename)
        page_content = self.to_html(page_source)
        return self.render_template('page.html', page_title=page_title, page_content=page_content)
    
    def edit_page(self, filename):
        page_title = filename_to_title(filename)
        try:
            page_source = self.get_page(filename)
        except FileNotFoundError:
            page_source = ''
        
        page_content = self.to_html(page_source)
        return self.render_template('edit.html', page_title=page_title, page_content=page_content)
    
    def save_page(self, filename, request):
        old_title = request.form['oldtitle'].strip()
        title = request.form['title'].strip()
        if old_title != title:
            try:
                old_path = self.safe_file_path('pages', old_title)
            except FileNotFoundError:
                old_path = None
            
            if old_path and os.path.isfile(old_path):
                with open('old_path', 'w') as file:
                    print('=> %s' % title_to_filename(title), file=file)
        
        html = sanitize_html(request.form['content'])
        filename = title_to_filename(title)
        with open(self.safe_file_path('pages', filename), 'w', encoding='utf-8') as file:
            file.write(self.to_source(html))
        
        if 'headerimage' in request.files:
            header_image = request.files['headerimage'].read()
            extension = mimetypes.guess_extension(request.files['headerimage'].mimetype)
            if extension == '.jpe': extension = '.jpg' # wtf Python?!
            if extension in Ikwi.image_extensions:
                image_filename = filename + extension
                for other_extension in Ikwi.image_extensions:
                    try:
                        os.unlink(self.safe_file_path('images', filename + other_extension))
                    except FileNotFoundError: pass
                
                with open(self.safe_file_path('images', image_filename), 'wb') as file:
                    file.write(header_image)
                    file.flush()
        
        return self.show_page(title_to_filename(title))

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
        return Response(
            "unauthorized!",
            401,
            {
                'WWW-Authenticate': 'Basic realm="%s"' % self.config['site_title']
            }
        )
    
    def not_found(self):
        return Response(
            "unfound!",
            404
        )

    # gitify
    def safe_file_path(self, directory, file): # 'safe' = famous last words
        file_path = os.path.join(self.site_base, directory, file)
        file_path = os.path.realpath(file_path)

        if not file_path.startswith(self.site_base + '/'):
            raise FileNotFoundError
        
        return file_path
    
    def file_from_directory(self, directory, file):
        file_path = self.safe_file_path(directory, file)
        file_type, file_encoding = mimetypes.guess_type(file_path)
        try:
            file = open(file_path, 'rb') # server closes this for us
        except FileNotFoundError:
            return self.not_found()

        return Response(file, mimetype=file_type, direct_passthrough=True)
