from stgit import argparse, utils
from stgit.argparse import opt
from stgit.commands.common import (
    CmdException,
    DirectoryHasRepository,
    get_public_ref,
    update_commit_data,
)
from stgit.lib.git import CommitData, Person
from stgit.lib.transaction import StackTransaction
from stgit.out import out

__copyright__ = """
Copyright (C) 2009, Catalin Marinas <catalin.marinas@gmail.com>

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License version 2 as
published by the Free Software Foundation.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, see http://www.gnu.org/licenses/.
"""

help = '(DEPRECATED) Push the stack changes to a merge-friendly branch'
kind = 'stack'
usage = ['[options] [--] [branch]']
description = """
DEPRECATED: The 'stg publish' command will be removed in a future version of
StGit.

This command commits a set of changes on a separate (called public) branch
based on the modifications of the given or current stack. The history of the
public branch is not re-written, making it merge-friendly and feasible for
publishing. The heads of the stack and public branch may be different but the
corresponding tree objects are always the same.

If the trees of the stack and public branch are different (otherwise the
command has no effect), StGit first checks for a rebase of the stack since the
last publishing. If a rebase is detected, StGit creates a commit on the public
branch corresponding to a merge between the new stack base and the latest
public head.

If no rebasing was detected, StGit checks for new patches that may have been
created on top of the stack since the last publishing. If new patches are
found and are not empty, they are checked into the public branch keeping the
same commit information (e.g. log message, author, committer, date).

If the above tests fail (e.g. patches modified or removed), StGit creates a
new commit on the public branch having the same tree as the stack but the
public head as its parent. The editor will be invoked if no "--message" option
is given.

It is recommended that stack modifications falling in different categories as
described above are separated by a publish command in order to keep the public
branch history cleaner (otherwise StGit would generate a big commit including
several stack modifications).

The '--unpublished' option can be used to check if there are applied patches
that have not been published to the public branch. This is done by trying to
revert the patches in the public tree (similar to the 'push --merged'
detection). The '--last' option tries to find the last published patch by
checking the SHA1 of the patch tree agains the public tree. This may fail if
the stack was rebased since the last publish command.

The public branch name can be set via the branch.<branch>.public configuration
variable (defaulting to "<branch>.public").
"""

args = ['all_branches']
options = [
    opt(
        '-b',
        '--branch',
        args=['stg_branches'],
        short='Use BRANCH instead of the default branch',
    ),
    opt('-l', '--last', action='store_true', short='Show the last published patch',),
    opt(
        '-u',
        '--unpublished',
        action='store_true',
        short='Show applied patches that have not been published',
    ),
    opt(
        '--overwrite',
        action='store_true',
        short='Overwrite branch instead of creating new commits',
    ),
] + (
    argparse.author_options()
    + argparse.message_options(save_template=False)
    + argparse.sign_options()
)

directory = DirectoryHasRepository()


def __create_commit(repository, tree, parents, options, message=''):
    """Return a new Commit object."""
    cd = CommitData(
        tree=tree,
        parents=parents,
        message=message,
        author=Person.author(),
        committer=Person.committer(),
    )
    cd = update_commit_data(
        cd,
        message=options.message,
        author=options.author(cd.author),
        sign_str=options.sign_str,
        edit=options.message is None,
    )
    return repository.commit(cd)


def __get_published(stack, tree):
    """Check the patches that were already published."""
    trans = StackTransaction(stack, 'publish')
    published = trans.check_merged(trans.applied, tree=tree, quiet=True)
    trans.abort()
    return published


def __get_last(stack, tree):
    """Return the name of the last published patch."""
    for p in reversed(stack.patchorder.applied):
        pc = stack.patches.get(p).commit
        if tree.sha1 == pc.data.tree.sha1:
            return p
    return None


def func(parser, options, args):
    """Publish the stack changes."""
    out.warn('DEPRECATED: stg publish will be removed in a future version of StGit.')
    repository = directory.repository
    stack = repository.get_stack(options.branch)

    if not args:
        public_ref = get_public_ref(stack.name)
    elif len(args) == 1:
        public_ref = args[0]
    else:
        parser.error('incorrect number of arguments')

    if not public_ref.startswith('refs/heads/'):
        public_ref = 'refs/heads/' + public_ref

    # just clone the stack if the public ref does not exist
    if not repository.refs.exists(public_ref):
        if options.unpublished or options.last:
            raise CmdException('"%s" does not exist' % public_ref)
        repository.refs.set(public_ref, stack.head, 'publish')
        out.info('Created "%s"' % public_ref)
        return

    public_head = repository.refs.get(public_ref)
    public_tree = public_head.data.tree

    # find the last published patch
    if options.last:
        last = __get_last(stack, public_tree)
        if not last:
            raise CmdException(
                'Unable to find the last published patch ' '(possibly rebased stack)'
            )
        out.info('%s' % last)
        return

    # check for same tree (already up to date)
    if public_tree.sha1 == stack.head.data.tree.sha1:
        out.info('"%s" already up to date' % public_ref)
        return

    # check for unpublished patches
    if options.unpublished:
        published = set(__get_published(stack, public_tree))
        for p in stack.patchorder.applied:
            if p not in published:
                out.stdout(p)
        return

    if options.overwrite:
        repository.refs.set(public_ref, stack.head, 'publish')
        out.info('Overwrote "%s"' % public_ref)
        return

    # check for rebased stack. In this case we emulate a merge with the stack
    # base by setting two parents.
    merge_bases = set(repository.get_merge_bases(public_head, stack.base))
    if public_head in merge_bases:
        # fast-forward the public ref
        repository.refs.set(public_ref, stack.head, 'publish')
        out.info('Fast-forwarded "%s"' % public_ref)
        return
    if stack.base not in merge_bases:
        message = 'Merge %s into %s' % (
            repository.describe(stack.base).strip(),
            utils.strip_prefix('refs/heads/', public_ref),
        )
        public_head = __create_commit(
            repository,
            stack.head.data.tree,
            [public_head, stack.base],
            options,
            message,
        )
        repository.refs.set(public_ref, public_head, 'publish')
        out.info('Merged the stack base into "%s"' % public_ref)
        return

    # check for new patches from the last publishing. This is done by checking
    # whether the public tree is the same as the bottom of the checked patch.
    # If older patches were modified, new patches cannot be detected. The new
    # patches and their metadata are pushed directly to the published head.
    for p in stack.patchorder.applied:
        pc = stack.patches.get(p).commit
        if public_tree.sha1 == pc.data.parent.data.tree.sha1:
            if pc.data.is_nochange():
                out.info('Ignored new empty patch "%s"' % p)
                continue
            cd = pc.data.set_parent(public_head)
            public_head = repository.commit(cd)
            public_tree = public_head.data.tree
            out.info('Published new patch "%s"' % p)

    # create a new commit (only happens if no new patches are detected)
    if public_tree.sha1 != stack.head.data.tree.sha1:
        public_head = __create_commit(
            repository, stack.head.data.tree, [public_head], options
        )

    # update the public head
    repository.refs.set(public_ref, public_head, 'publish')
    out.info('Updated "%s"' % public_ref)
