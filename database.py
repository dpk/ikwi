# TODO: implement this only in terms of storage, not using Git directly
import os
import os.path
import time

# common functionality for the search and links databases
class Database:
    def __init__(self, site):
        self.site = site

    @property
    def path(self):
        return os.path.join(self.site.storage.repo.path, type(self).database_name) # come at me, Demeter!
    
    @property
    def outdated(self):
        try:
            with open(self.path + '.head', 'r', encoding='us-ascii') as f:
                db_version = f.read().strip()
                site_version = self.site.latest.revision
                return db_version != site_version
        except FileNotFoundError:
            return True
    
    @property
    def current_version(self):
        with open(self.path + '.head', 'r', encoding='us-ascii') as f:
            return f.read().strip()
    
    def update(self, tries=20):
        if not self.outdated: return
        try:
            lock_file = None
            try:
                lock_file = open(self.path + '.head.lock', 'x', encoding='us-ascii') 
                repo = self.site.storage.repo
                
                try:
                    db_version = self.current_version
                    
                    print(db_version, file=lock_file)
                    lock_file.flush()
                    lock_file.seek(0)
                
                    old_tree = repo[repo[db_version].tree['pages'].id]
                    new_tree = repo[repo[self.site.latest.revision].tree['pages'].id]
                
                    differences = {}
                    for page in new_tree:
                        if page.name not in old_tree:
                            differences[page.name] = ('created', repo[page.id].data)
                        elif old_tree[page.name].id != new_tree[page.name].id:
                            differences[page.name] = ('updated', repo[page.id].data)
                
                    for page in old_tree:
                        if page.name not in new_tree:
                            differences[page.name] = ('deleted', None)
                except FileNotFoundError:
                    self.do_create()
                    tree = repo[repo[self.site.latest.revision].tree['pages'].id]
                    differences = {}
                    for page in tree:
                        differences[page.name] = ('created', repo[page.id].data)
                
                self.do_update(differences)
                
                print(self.site.latest.revision, file=lock_file)
                lock_file.flush()
            finally:
                if lock_file and not lock_file.closed:
                    lock_file.close()
                os.rename(self.path + '.head.lock', self.path + '.head')
        except FileExistsError:
            if tries > 0:
                time.sleep(0.1)
                self.update(tries=tries - 1)
            else:
                raise
