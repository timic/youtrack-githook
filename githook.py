#!/usr/bin/env python
# -*- coding: utf-8 -*=

import re
from datetime import datetime
from types import ListType, StringType

from flask import request, Response, Flask

from youtrack import YouTrackException
from youtrack.connection import Connection

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
    """
    Ping
    :rtype: StringType
    :return:
    """
    return 'ping'


@app.route('/hook', methods=['POST'])
@app.route('/push_event', methods=['POST'])
def push_event_hook():
    """
    Web-hook for push event
    :rtype: Response
    :return:
    """
    push_event = request.json
    process_push_event(push_event)

    return Response('Push event processed. Thanks!', mimetype='text/plain')


def process_push_event(push_event):
    """
    Processes the push event provided: collects comments and publishes them to YouTrack
    :param push_event:
    :rtype: NoneType
    :return:
    """
    comments = collect_comments_for_issues(push_event)
    publish_to_youtrack(comments)


def collect_comments_for_issues(push_event):
    """
    Aggregates (collects) comments per each issue associated with commit(s) provided via the push event
    :rtype: ListType
    :param push_event:
    :return: List of structures (dictionaries) having the following keys: issue_id, author_email, commit_time,
    comment_string
    """
    app.logger.debug(push_event)
    repo_name = push_event['repository']['name']
    repo_project = push_event['repository']['project']['key']
    repo_slug = push_event['repository']['slug']
    stash_host = app.config['STASH_HOST']
    repo_homepage = '/'.join([stash_host, 'projects', repo_project, 'repos', repo_slug])
    ref_spec = push_event['refChanges'][-1]['refId'].replace('refs/heads/', '')

    app.logger.debug(u'Received push event in branch %s on repository %s', ref_spec, repo_name)

    change_sets = push_event['changesets']['values']
    commit_list = map(lambda cs: cs['toCommit'], change_sets)

    commit_map = dict(zip(map(lambda c: c['id'], commit_list), commit_list))

    result = list()

    for commit_id in commit_map.keys():
        commit = commit_map[commit_id]
        commit_url = '/'.join([repo_homepage, 'commits', commit['id']])
        author_email = commit['author']['emailAddress']
        app.logger.debug(
                u'Processing commit %s by %s (%s) in %s',
                commit['id'],
                commit['author']['name'],
                author_email,
                commit_url,
        )
        commit_time = datetime.fromtimestamp(commit['authorTimestamp'] / 1000)
        issues = re.findall(app.config['REGEX'], commit['message'], re.MULTILINE)

        if not issues:
            app.logger.debug(u'''Didn't find any referenced issues in commit %s''', commit['id'])
        else:
            app.logger.debug(u'Found %d referenced issues in commit %s', len(issues), commit['id'])

            for issue_id in frozenset(issues):
                app.logger.debug(u'Processing reference to issue %s', issue_id)
                comment_string = (
                    u'=Git Commit=\n\n'
                    u'{monospace}\n'
                    u'*id*: [%(url)s %(id)s]\n'
                    u'*author*: %(author)s\n'
                    u'*branch*: %(ref_spec)s\n'
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
                        'ref_spec': ref_spec
                    })
                app.logger.debug(comment_string)

                result.append({
                    'issue_id': issue_id,
                    'author_email': author_email,
                    'commit_time': commit_time,
                    'comment_string': comment_string
                })

    return sorted(result, key=lambda r: r['commit_time'])


def publish_to_youtrack(comments):
    """
    Publishes the comment string to the issue identified on behalf of the author (if the email matches one)
    :rtype: NoneType
    :param comments:
    :return: Nothing
    """
    yt = Connection(app.config['YOUTRACK_URL'], app.config['YOUTRACK_USERNAME'], app.config['YOUTRACK_PASSWORD'])

    for comment in comments:
        issue_id = comment['issue_id']
        comment_string = comment['comment_string']
        author_email = comment['author_email']

        user_login = get_user_login(yt, author_email)
        if user_login is None:
            app.logger.warn(u"Couldn't find user with email address %s. Using default user.", author_email)
            default_user = yt.getUser(app.config['DEFAULT_USER'])
            user_login = default_user['login']

        try:
            yt.getIssue(issue_id)
            yt.executeCommand(
                issueId=issue_id, command='comment', comment=comment_string.encode('utf-8'),
                run_as=user_login.encode('utf-8'), disable_notifications=True)
        except YouTrackException:
            app.logger.warn("Couldn't find issue %s", issue_id)


def get_user_login(yt, email):
    """
    Given a youtrack connection and an email address, try to find the login
    name for a user. Returns `None` if no (unique) user was found.
    :param yt:
    :param email:
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
