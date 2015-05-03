"""
storage -- tidemark git in a way that's useful for building web-apps
"""
# ᚾᚪᚻᛏ᛫ᛁᛋ᛫ᚦᚱᚫᛞᛋᛁᚳᚩᚱ
# todo: straighten out the terminology used here ('store' and 'storage'; 'commit_id', 'commit', and 'revision')
# merge conflict resolution API probably needs a little tweaking

from collections import deque
import os
import os.path
import time
import warnings

import pygit2


def commit_id(id):
    if isinstance(id, pygit2.Oid):
        return str(id)
    elif isinstance(id, str):
        return id
    elif isinstance(id, bytes):
        return ''.join('%02x' % byte for byte in id)
    else:
        raise TypeError('commit_id() argument must be Oid, str, or bytes')

class NoConflictError(Exception): pass
class Storage:
    def __init__(self, repo_path):
        self.repo = pygit2.Repository(repo_path)
    
    def cursor(self, base_commit):
        return Cursor(self, commit_id(base_commit))
    
    def latest(self):
        head_commit = self.repo[self.repo.head.resolve().target]
        return StorageRevision(self, head_commit.id, head_commit.tree)
    
    def merge_conflict(self, source_revision, target_revision):
        merge = self.repo.merge_commits(target_revision, source_revision)
        if not merge.conflicts:
            raise NoConflictError('an attempt was made to resolve a conflict when merging from %r into %r, but no conflict exists between those revisions' % (source_revision, target_revision))
        
        return MergeConflict(self, source_revision, target_revision, merge.conflicts)
    
    def ref_lock(self, ref, *, spin_tries=0, spin_wait=0.2):
        lock = None
        while spin_tries >= 0:
            try:
                lock = ReferenceLock(self.repo, ref)
                break
            except ReferenceLockedError:
                if spin_tries == 0:
                    raise
                else:
                    spin_tries -= 1
                    time.sleep(spin_wait)
        
        return lock

class StorageRevision:
    def __init__(self, storage, revision, tree, root_tree=None):
        self.storage = storage
        self.revision = commit_id(revision)
        self.tree = tree
        if not root_tree:
            self.root_tree = tree
        else:
            self.root_tree = root_tree
    
    def __contains__(self, filename):
        return (filename in self.tree) and (self.tree[filename].filemode == pygit2.GIT_FILEMODE_BLOB)
    
    def get_id(self, filename):
        tree_entry = self.tree[filename]
        return str(tree_entry.id)
    
    def get(self, filename):
        if filename not in self.tree: return None
        tree_entry = self.tree[filename]
        if tree_entry.filemode != pygit2.GIT_FILEMODE_BLOB: return None
        blob = self.storage.repo[tree_entry.id]
        return blob.data
    
    def dir(self, dirname):
        if dirname not in self.tree: return EmptyStorageRevision()
        tree_entry = self.tree[dirname]
        if tree_entry.filemode != pygit2.GIT_FILEMODE_TREE: return EmptyStorageRevision()
        tree = self.storage.repo[tree_entry.id]
        return StorageRevision(self.storage, self.revision, tree, self.root_tree)

# this needs a better API
class EmptyStorageRevision:
    def get(self, filename): return None

class InvalidOperationError(Exception): pass
class Cursor:
    def __init__(self, storage, base_commit, *, original_base_commit=None):
        self.storage = storage
        self.repo = self.storage.repo
        self.base_commit_id = commit_id(base_commit)
        
        if original_base_commit:
            self.original_base_commit_id = commit_id(original_base_commit)
        else:
            self.original_base_commit_id = commit_id(base_commit)
        
        self.root_tree = self.repo[base_commit].tree
    
    def add(self, path, contents):
        blob_id = self.repo.create_blob(contents)
        idx = pygit2.Index()
        idx.read_tree(self.root_tree)
        
        invalid = False
        try:
            idx.add(pygit2.IndexEntry(path, blob_id, pygit2.GIT_FILEMODE_BLOB))
        except pygit2.GitError as err:
            if 'appears as both a file and a directory' in err.args[0]:
                invalid = True
        
        if invalid:
            raise InvalidOperationError('refusing to replace another kind of object with a tree')

        tree_id = idx.write_tree(self.repo)
        self.root_tree = self.repo[tree_id]

    def delete(self, path):
        idx = pygit2.Index()
        idx.read_tree(self.root_tree)
        
        try:
            idx.remove(path)
        except OSError:
            return False
        
        tree_id = idx.write_tree(self.repo)
        self.root_tree = self.repo[tree_id]
        return True
    
    def save(self, message, author, committer=None):
        if committer == None: committer = author
        new_commit_id = self.repo.create_commit(
            None, # reference
            author,
            committer,
            message,
            self.root_tree.id, # tree
            [self.base_commit_id] # parents
        )
        self.base_commit_id = commit_id(new_commit_id)
    
    def update(self, ref='HEAD', *, merger=None, spin_tries=10, spin_wait=0.2):
        if not merger:
            committer = self.repo[self.base_commit_id].committer
            merger = Signature(committer.name, committer.email)
        
        with self.storage.ref_lock(ref, spin_tries=spin_tries, spin_wait=0.2) as lock:
            if commit_id(self.repo.lookup_reference(lock.ref_name).target) == self.original_base_commit_id:
                # no other changes meanwhile
                lock.set_target(self.base_commit_id)
                return NoMergeWasNeeded(self.repo[self.base_commit_id])
            else:
                merge = self.repo.merge_commits(self.repo.lookup_reference(lock.ref_name).target, self.base_commit_id)
                if merge.conflicts:
                    return MergeConflict(self.storage, self.base_commit_id, self.repo.lookup_reference(lock.ref_name).target, merge.conflicts)
                else:
                    merge_tree = merge.write_tree(self.repo)
                    merge_commit_id = self.repo.create_commit(
                        None, # reference
                        merger, # author
                        merger, # committer
                        ('Merge commit %r into %r' % (self.base_commit_id, lock.ref_name)), # message
                        merge_tree, # tree
                        [self.repo.lookup_reference(lock.ref_name).target, self.base_commit_id] # parents
                    )
                    lock.set_target(merge_commit_id)
                    return AutoMerged(self.repo[merge_commit_id])

class UpdateResult:
    def __init__(self, commit):
        self.commit = commit
        self.revision = commit_id(commit.id)
    
    @property
    def merged(self): return len(self.commit.parents) > 1
    
    @property
    def conflict(self): return False

class NoMergeWasNeeded(UpdateResult): pass
class AutoMerged(UpdateResult): pass

class MergeConflictUnresolved(Exception): pass
class MergeConflict(UpdateResult):
    def __init__(self, store, source_revision, target_revision, conflicts):
        self.store = store
        self.source_revision = commit_id(source_revision)
        self.target_revision = commit_id(target_revision)
        
        self.conflicts = {}
        for original, target_version, source_version in conflicts:
            def version_content(version):
                if version is None: return None
                return self.store.repo[version.hex].data
            
            path = [v for v in (original, target_version, source_version) if v][0].path
            self.conflicts[path] = ConflictedFile(
                original=version_content(original),
                source_version=version_content(source_version),
                target_version=version_content(target_version)
            )

    @property
    def conflict(self): return True

    def resolve(self, resolutions, merger=None):
        repo = self.store.repo
        if not merger:
            committer = repo[self.source_revision].committer
            merger = Signature(committer.name, committer.email)
        
        merge = self.store.repo.merge_commits(self.source_revision, self.target_revision)
        
        for path, resolution in resolutions.items():
            blob_id = repo.create_blob(resolution)
            merge.add(pygit2.IndexEntry(path, blob_id, pygit2.GIT_FILEMODE_BLOB))
            del merge.conflicts[path]
        
        if merge.conflicts:
            raise MergeConflictUnresolved('not all the conflicts between %r and %r were resolved' % (source_revision, target_revision))
        
        merge_tree = merge.write_tree(repo)
        merge_commit_id = repo.create_commit(
            None, # reference
            merger,
            merger,
            ('Merge commit %r with %r' % (self.source_revision, self.target_revision)),
            merge_tree,
            [self.target_revision, self.source_revision]
        )
        
        return Cursor(self.store, merge_commit_id, original_base_commit=self.target_revision)

class ConflictedFile:
    __all__ = ('original', 'source_version', 'target_version')
    def __init__(self, original, source_version, target_version):
        self.original = original
        self.source_version = source_version
        self.target_version = target_version
    
    def __eq__(self, other):
        if not isinstance(other, ConflictedFile): return False
        return (self.original == other.original) and (self.source_version == other.source_version) and (self.target_version == other.target_version)

# we might need to overload more functionality onto Signature one day, but for now this will do:
Signature = pygit2.Signature

# when pygit2 implements transactions we can get rid of this
class ReferenceLockedError(Exception): pass
class UnsavedReferenceLockWarning(Warning): pass
class ReferenceLock:
    def __init__(self, repo, ref_name):
        self.repo = repo
        # canonicalize the name
        ref = self.repo.lookup_reference(ref_name).resolve()
        self.ref_name = ref.name
        self.original_target = commit_id(ref.target)
        
        self.lock_file_path = os.path.join(self.repo.path, self.ref_name + '.lock')
        try:
            self.lock_file = open(self.lock_file_path, 'x', encoding='us-ascii')
        except FileExistsError:
            raise ReferenceLockedError('reference %r on repo %r is already locked' % (self.ref_name, self.repo.path))
        
        self.set_target(ref.target)
    
    def set_target(self, target):
        target = commit_id(target)
        self.lock_file.seek(0)
        print(target, file=self.lock_file)
        # for safety:
        self.lock_file.flush()
        self.lock_file.truncate(self.lock_file.tell())
    
    def revert(self): return self.set_target(self.original_target)
    
    def save(self):
        self.lock_file.close()
        os.rename(self.lock_file_path, os.path.join(self.repo.path, self.ref_name))
    
    def __enter__(self): return self
    def __exit__(self, *exc_info): self.save()
    
    def __del__(self):
        if not self.lock_file.closed:
            self.lock_file.close()
            os.remove(self.lock_file_path)
            warnings.warn('a reference lock for %r on repository %r was deleted without being saved' % (self.ref_name, self.repo.path), UnsavedReferenceLockWarning)
