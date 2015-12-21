#!/usr/bin/env python
# -*- coding: utf-8 -*=

import re
from collections import OrderedDict
from datetime import datetime
from flask import Flask, request, Response
from youtrack.connection import Connection
from youtrack import YouTrackException

# Configuration
YOUTRACK_URL = ''
YOUTRACK_USERNAME = ''
YOUTRACK_PASSWORD = ''
YOUTRACK_APIKEY = ''
STASH_HOST = ''
REGEX = '([A-Z]+-\d+)'
DEFAULT_USER = ''

app = Flask(__name__)
app.config.from_object(__name__)
app.config.from_pyfile('settings.cfg', silent=True)
app.config.from_envvar('GITHOOK_SETTINGS', silent=True)


# Application
@app.route('/')
def ping():
    return 'ping'


@app.route('/hook', methods=['POST'])
@app.route('/push_event', methods=['POST'])
def push_event_hook():
    push_event = request.json
    app.logger.debug(push_event)
    repo_name = push_event['repository']['name']
    repo_project = push_event['repository']['project']['key']
    repo_slug = push_event['repository']['slug']
    stash_host = app.config['STASH_HOST']
    repo_homepage = "/".join([stash_host, "projects", repo_project, "repos", repo_slug])
    refspec = push_event['refChanges'][-1]['refId'].replace("refs/heads/", "")

    app.logger.debug(u'Received push event in branch %s on repository %s', refspec, repo_name)
    commit_ids = [it['id'] for it in reversed(push_event['changesets']['values'])]
    commit_map = OrderedDict()
    for it in push_event['changesets']['values']:
        commit_map[it["id"]] = it
        
    for commit in commit_map.keys():
        commit = commit['toCommit']
        commit_url = "/".join([repo_homepage, "commits", commit['id']])
        app.logger.debug(
            u'Processing commit %s by %s (%s) in %s',
            commit['id'],
            commit['author']['name'],
            commit['author']['emailAddress'],
            commit_url,
        )
        commit_time = datetime.fromtimestamp(commit['authorTimestamp']/1000)
        issues = re.findall(app.config['REGEX'], commit['message'], re.MULTILINE)
        if not issues:
            app.logger.debug(u'''Didn't find any referenced issues in commit %s''', commit['id'])
        else:
            app.logger.debug(u'Found %d referenced issues in commit %s', len(issues), commit['id'])
            yt = Connection(
                app.config['YOUTRACK_URL'], app.config['YOUTRACK_USERNAME'], app.config['YOUTRACK_PASSWORD'])

            user_login = get_user_login(yt, commit['author']['emailAddress'])
            if user_login is None:
                app.logger.warn(
                    u"Couldn't find user with email address %s. Using default user.", commit['author']['emailAddress'])
                default_user = yt.getUser(app.config['DEFAULT_USER'])
                user_login = default_user['login']

            for issue_id in issues:
                app.logger.debug(u'Processing reference to issue %s', issue_id)
                try:
                    yt.getIssue(issue_id)
                    comment_string = (
                        u'=Git Commit=\n\n'
                        u'{monospace}\n'
                        u'*id*: [%(url)s %(id)s]\n'
                        u'*author*: %(author)s\n'
                        u'*branch*: %(refspec)s\n'
                        u'*repository*: [%(repo_homepage)s %(repo_name)s]\n'
                        u'*timestamp*: %(date)s UTC\n'
                        u'{monospace}\n\n'
                        u'====Message====\n\n'
                        u'{monospace}\n'
                        u'%(message)s\n'
                        u'{monospace}'
                        % {
                            'url': commit_url,
                            'id': commit['displayId'],
                            'author': commit['author']['name'],
                            'date': str(commit_time),
                            'message': commit['message'],
                            'repo_homepage': repo_homepage,
                            'repo_name': repo_name,
                            'refspec': refspec
                        })
                    app.logger.debug(comment_string)
                    yt.executeCommand(issueId=issue_id, command='comment', comment=comment_string.encode('utf-8'),
                                      run_as=user_login.encode('utf-8'))
                except YouTrackException:
                    app.logger.warn("Couldn't find issue %s", issue_id)
    return Response('Push event processed. Thanks!', mimetype='text/plain')


def get_user_login(yt, email):
    """Given a youtrack connection and an email address, try to find the login
    name for a user. Returns `None` if no (unique) user was found.
    """
    users = yt.getUsers({'q': email})
    if len(users) == 1:
        return users[0]['login']
    else:
        # Unfortunately, youtrack does not seem to have an exact search
        for user in users:
            try:
                full_user = yt.getUser(user['login'])
            except YouTrackException:
                pass
            else:
                if full_user['email'] == email:
                    return full_user['login']
    return None


if __name__ == '__main__':
    app.run(threaded=True)
