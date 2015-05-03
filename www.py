"""
www -- minimal web framework, a customized version of Werkzeug
"""
import json

from werkzeug.wrappers import Request as BaseRequest, Response
from werkzeug.serving import run_simple
from werkzeug.datastructures import ImmutableOrderedMultiDict


class Request(BaseRequest):
    parameter_storage_class = ImmutableOrderedMultiDict
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        args_iterator = iter(self.args.items())
        try:
            key, value = next(args_iterator)
            if value == '':
                self.query_verb = key
                self.args = ImmutableOrderedMultiDict(args_iterator)
            else:
                self.query_verb = None
        except StopIteration:
            self.query_verb = None

# class Response(BaseResponse): pass

def JSONResponse(obj, code=200, headers={}):
    return Response(
        json.dumps(obj),
        code,
        headers.update({'Content-Type': 'application/json'})
    )

class MethodNotAllowed(Exception): pass
class Application:
    def wsgi_app(self, environ, start_response):
        request = Request(environ)
        self.before_request(request)
        
        try:
            response = self.dispatch_request(request)
        except FileNotFoundError:
            response = self.not_found()
        except PermissionError:
            response = self.unauthorized()
        except MethodNotAllowed:
            response = Response('Method %s is not allowed on this resource.' % (request.method), 405)
        
        return response(environ, start_response)

    def __call__(self, environ, start_response):
        return self.wsgi_app(environ, start_response)

    def run(self):
        run_simple('127.0.0.1', 3000, self, use_debugger=True)
    
    def require_method(self, request, methods):
        if request.method not in methods:
            raise MethodNotAllowed
