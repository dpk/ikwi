import gc
from os import system, mkdir
import uuid
import shutil

import pygit2
import pytest

from storage import *


def random_repository_path(bare=True):
    return '/tmp/%s%s' % (uuid.uuid4(), '.git' if bare else '')

@pytest.fixture
def repo(request):
    bare_path = random_repository_path()
    system('git init --bare ' + bare_path)

    unbare_path = random_repository_path(False)
    system('git clone ' + bare_path + ' ' + unbare_path)

    with open(unbare_path + '/test1.txt', 'w') as file: print('the first test file', file=file)
    system('git --git-dir=' + unbare_path + '/.git --work-tree=' + unbare_path + ' add ' + unbare_path + '/test1.txt')
    system('git --git-dir=' + unbare_path + '/.git --work-tree=' + unbare_path + ' commit -m "initial commit"')

    with open(unbare_path + '/test2.txt', 'w') as file: print('a second test file', file=file)
    system('git --git-dir=' + unbare_path + '/.git --work-tree=' + unbare_path + ' add ' + unbare_path + '/test2.txt')

    os.mkdir(unbare_path + '/test_tree')
    with open(unbare_path + '/test_tree/tree_test.txt', 'w') as file: print('a test file inside a tree', file=file)
    system('git --git-dir=' + unbare_path + '/.git --work-tree=' + unbare_path + ' add ' + unbare_path + '/test_tree/tree_test.txt')

    system('git --git-dir=' + unbare_path + '/.git --work-tree=' + unbare_path + ' commit -m "second commit"')
    system('git --git-dir=' + unbare_path + '/.git --work-tree=' + unbare_path + ' push -u origin master')

    shutil.rmtree(unbare_path)
    request.addfinalizer(lambda: shutil.rmtree(bare_path))

    return pygit2.Repository(bare_path)


def test_creating_cursor(repo):
    store = Storage(repo.path)
    assert(store.cursor(repo.head.target))

def test_add_file_to_cursor(repo):
    store = Storage(repo.path)
    cursor = store.cursor(repo.head.target)

    file_contents = b"the third test file\n"
    cursor.add('test3.txt', file_contents)
    assert('test3.txt' in cursor.root_tree)
    assert(repo[cursor.root_tree['test3.txt'].id].data == file_contents)

def test_add_file_inside_new_tree_to_cursor(repo):
    store = Storage(repo.path)
    cursor = store.cursor(repo.head.target)

    file_contents = b"a test file in a new tree\n"
    cursor.add('a_tree/test3.txt', file_contents)
    assert('a_tree' in cursor.root_tree)

    subtree = repo[cursor.root_tree['a_tree'].id]
    assert(subtree.type == pygit2.GIT_OBJ_TREE)
    assert('test3.txt' in subtree)
    assert(repo[subtree['test3.txt'].id].data == file_contents)

def test_add_file_inside_existing_tree_to_cursor(repo):
    store = Storage(repo.path)
    cursor = store.cursor(repo.head.target)

    file_contents = b"a test file in an existing tree\n"
    cursor.add('test_tree/tree_test2.txt', file_contents)
    assert('test_tree' in cursor.root_tree)

    subtree = repo[cursor.root_tree['test_tree'].id]
    assert(subtree.type == pygit2.GIT_OBJ_TREE)
    assert('tree_test2.txt' in subtree)
    assert(repo[subtree['tree_test2.txt'].id].data == file_contents)

def test_add_file_inside_new_tree_inside_existing_tree_to_cursor(repo):
    store = Storage(repo.path)
    cursor = store.cursor(repo.head.target)

    file_contents = b"a test file in a new tree, which is in turn inside an existing tree\n"
    cursor.add('test_tree/test_subtree/test.txt', file_contents)
    
    tree = repo[cursor.root_tree['test_tree'].id]
    assert('test_subtree' in tree)
    
    subtree = repo[tree['test_subtree'].id]
    assert(subtree.type == pygit2.GIT_OBJ_TREE)
    assert('test.txt' in subtree)
    assert(repo[subtree['test.txt'].id].data == file_contents)

def test_dont_replace_blobs_with_trees(repo):
    store = Storage(repo.path)
    cursor = store.cursor(repo.head.target)

    with pytest.raises(InvalidOperationError) as excinfo:
        cursor.add('test2.txt/testfail.txt', b"a test file that shouldn't work\n")

    assert('refusing to replace another kind of object with a tree' in str(excinfo.value))

def test_save_cursor(repo):
    store = Storage(repo.path)
    cursor = store.cursor(repo.head.target)
    
    commit_message = 'add a third test file\n'
    file_contents = b"a test file which will be saved to a commit (but not merged)"
    cursor.add('test3.txt', file_contents)
    cursor.save(commit_message, author=Signature('Test User', 'tester@example.org'))
    
    assert(cursor.base_commit_id in repo)
    
    commit = repo[cursor.base_commit_id]
    assert(commit.message == commit_message)
    
    commit_tree = commit.tree
    assert('test3.txt' in commit_tree)
    
    new_blob = repo[commit_tree['test3.txt'].id]
    assert(new_blob.data == file_contents)

def test_save_cursor_and_update_head(repo):
    store = Storage(repo.path)
    cursor = store.cursor(repo.head.target)
    
    commit_message = 'add a third test file\n'
    file_contents = b"a test file which will be saved to a commit, and have the HEAD updated"
    cursor.add('test3.txt', file_contents)
    cursor.save(commit_message, author=Signature('Test User', 'tester@example.org'))
    update_result = cursor.update('HEAD')
    
    assert(not update_result.merged)
    assert(str(repo.head.target) == cursor.base_commit_id)

def test_save_cursor_and_update_head_with_merge(repo):
    store = Storage(repo.path)
    
    initial_commit = repo[repo.head.target].parents[0].id
    cursor = store.cursor(initial_commit)
    
    commit_message = 'add a third test file\n'
    file_contents = b"a test file which will be saved to a commit, and have the HEAD updated and then merged"
    cursor.add('test3.txt', file_contents)
    cursor.save(commit_message, author=Signature('Test User', 'tester@example.org'))
    update_result = cursor.update('HEAD')
    
    assert(update_result.merged)
    assert(str(repo.head.target) != cursor.base_commit_id)
    assert(str(repo.head.target) == str(update_result.commit.id))
    
    tree = update_result.commit.tree
    assert(repo[tree['test1.txt'].id].data == b"the first test file\n")
    assert(repo[tree['test3.txt'].id].data == file_contents)

def test_cursor_update_ref_locking(repo, recwarn):
    store = Storage(repo.path)
    lock = store.ref_lock('HEAD')

    cursor = store.cursor(repo.head.target)
    cursor.save('a nothing commit', author=Signature('Test User', 'tester@example.org'))

    with pytest.raises(ReferenceLockedError):
        update_result = cursor.update('HEAD', spin_tries=0)
    
    del lock
    gc.collect() # for PyPy
    w = recwarn.pop(UnsavedReferenceLockWarning)
    assert issubclass(w.category, UnsavedReferenceLockWarning)

def test_save_cursor_and_update_head_with_merge_conflict(repo):
    store = Storage(repo.path)
    
    root_commit = repo.head.target
    cursor = store.cursor(root_commit)
    cursor.add('test3.txt', b"third test one\n")
    cursor.save('add a third test file', author=Signature('Test User', 'tester@example.org'))
    cursor.update('HEAD')
    
    cursor = store.cursor(root_commit)
    cursor.add('test3.txt', b"third test two\n")
    cursor.save('add a third test file (this should conflict)', author=Signature('Test User', 'tester@example.org'))
    
    update_result = cursor.update('HEAD')
    
    assert(update_result.conflict)
    assert('test3.txt' in update_result.conflicts)
    
    conflict_file = update_result.conflicts['test3.txt']
    assert(conflict_file.original == None)
    assert(conflict_file.source_version == b"third test two\n")
    assert(conflict_file.target_version == b"third test one\n")

def test_resolve_merge_conflict(repo):
    store = Storage(repo.path)
    
    root_commit = repo.head.target
    cursor = store.cursor(root_commit)
    cursor.add('test3.txt', b"third test one\n")
    cursor.save('add a third test file', author=Signature('Test User', 'tester@example.org'))
    cursor.update('HEAD')
    
    cursor = store.cursor(root_commit)
    cursor.add('test3.txt', b"third test two\n")
    cursor.save('add a third test file (this should conflict)', author=Signature('Test User', 'tester@example.org'))
    conflict = cursor.update('HEAD')
    
    merged_cursor = conflict.resolve({'test3.txt': b"third test merged\n"})
    update_result = merged_cursor.update('HEAD')
    
    assert(not update_result.conflict)
    assert(merged_cursor.base_commit_id == str(repo.head.target))
    
    tree = repo[repo.head.target].tree
    assert('test3.txt' in tree)
    assert(repo[tree['test3.txt'].id].data == b"third test merged\n")

def test_recreate_merge_conflict(repo):
    store = Storage(repo.path)
    
    root_commit = repo.head.target
    cursor = store.cursor(root_commit)
    cursor.add('test3.txt', b"third test one\n")
    cursor.save('add a third test file', author=Signature('Test User', 'tester@example.org'))
    cursor.update('HEAD')
    
    cursor = store.cursor(root_commit)
    cursor.add('test3.txt', b"third test two\n")
    cursor.save('add a third test file (this should conflict)', author=Signature('Test User', 'tester@example.org'))
    conflict = cursor.update('HEAD')
    
    recreated_conflict = store.merge_conflict(conflict.source_revision, conflict.target_revision)
    
    assert(conflict.conflicts == recreated_conflict.conflicts)
