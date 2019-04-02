from __future__ import print_function

import os
import logging
import re
from wsgiref.simple_server import make_server

from github import Github, GithubException
from pyramid.config import Configurator
from pyramid.view import view_config, view_defaults
from pyramid.response import Response

USERNAME = os.environ.get('GIT_USERNAME', None)
PASSWORD = os.environ['GIT_PASSWORD']
CALLBACK_PATH = os.environ['CALLBACK_PATH']
EXTERNAL_HOST = os.environ['EXTERNAL_HOST']
ORGANIZATION = os.enivron['ORGANIZATION']
LOGGING_LEVEL = os.environ.get('LOGGING_LEVEL', 'INFO')

MSG_ACK = """
@esgf-nimbus/admin Please review this application.
"""

MSG_INV = """
@{issue.user.login} You should recieve and invite to esgf-nimbus shortly.
"""

MSG_ADD = """
@{issue.user.login} You've been added to esgf-nimbus.

Before you can continue please set you organization visbility to [public](https://help.github.com/en/articles/publicizing-or-hiding-organization-membership)

Next visit https://aims2.llnl.gov/jupyterhub.
"""

DENIED_PATTERN = re.compile('deny|denied|reject|rejected', re.I)

logging.basicConfig(level=LOGGING_LEVEL)

def create_github_webhook(org):
    config = {
        'url': '{!s}/{!s}'.format(EXTERNAL_HOST, CALLBACK_PATH),
        'content_type': 'json',
    }

    logging.info('Attempting to register webhook on %s with payload %s', org.id, config)

    try:
        org.create_hook('web', config, ['issues', 'issue_comment', 'organization'], active=True)
    except GithubException as e:
        logging.info('Failed to register webhook status: %s reason: %s', e.status, e.data)

        pass
    else:
        logging.info('Successfully registered webhook')

if USERNAME is None:
    g = Github(PASSWORD)

    logging.info('Logging into Github with a token')
else:
    g = Github(USERNAME, PASSWORD)

    logging.info('Logging into Github with username/password')

org = g.get_organization(ORGANIZATION)

admin_id = [x.id for x in org.get_members(role='admin')]

logging.info('Retrieved organization %r', org.id)

create_github_webhook(org)

repo = g.get_repo('esgf-nimbus/getting_started')

awaiting = repo.get_label('awaiting-review')

logging.info('Retrieved repo %r', repo.id)

def check_denied(payload=None, issue=None):
    try:
        if payload is not None:
            repo_check = payload['repository']['id'] == repo.id
            admin_check = payload['comment']['user']['id'] in admin_id
            denied_check = DENIED_PATTERN.search(payload['comment']['body']) is not None

            if repo_check and admin_check and denied_check:
                issue = repo.get_issue(payload['issue']['id'])
        else:
            for comment in issue.get_comments():
                denied_check = DENIED_PATTERN.search(comment.body) is not None

                if denied_check:
                    break

        if denied_check:
            issue.edit(state='closed', labels=['request-denied',])

            logging.info('Found denied comment, closing issue')
        else:
            logging.info('Did not find a denied comment')
    except KeyError as e:
        logging.error('Missing key in payload %r', e)
    except GithubException as e:
        logging.error('Github error %r', e)

def notify_team(payload=None, issue=None):
    try:
        if payload is not None and payload['repository']['id'] == repo.id:
            issue = repo.get_issue(payload['issue']['id'])

        ack = False

        msg = MSG_ACK.format(issue=issue)

        for comment in issue.get_comments():
            if (comment.user.login == g.get_user().login and
                comment.body == msg):
                ack = True

                break

        if not ack:
            issue.create_comment(msg)
    except KeyError as e:
        logging.error('Missing key in payload %r', e)
    except GithubException as e:
        logging.error('Github error %r', e)

def notify_invite(payload):
    try:
        if payload['organization']['id'] == org.id:
            logging.info('Recieved an invite search for related issue')

            issues = repo.get_issues(state='opened', 
                                     labels=[awaiting_review,], 
                                     creator=payload['membership']['user']['login'])

            logging.info('Found %r issues', issues.totalCount)

            if issues.totalCount > 0:
                msg = MSG_INV.format(issue=issue)

                issues[0].create_comment(msg)
    except KeyError as e:
        logging.error('Missing key in payload %r', e)
    except GithubException as e:
        logging.error('Github error %r', e)

def notify_added(payload):
    try:
        if payload['organization']['id'] == org.id:
            logging.info('User added search for related issue')

            issues = repo.get_issues(state='opened', 
                                     labels=[awaiting_review,], 
                                     creator=payload['membership']['user']['login'])

            logging.info('Found %r issues', issues.totalCount)

            if issues.totalCount > 0:
                msg = MSG_ADD.format(issue=issue)

                issues[0].create_comment(msg)

                issues[0].edit(state='closed', labels=['request-approved',])
    except KeyError as e:
        logging.error('Missing key in payload %r', e)
    except GithubException as e:
        logging.error('Github error %r', e)

@view_defaults(route_name=CALLBACK_PATH, renderer='json', request_method='POST')
class PayloadView(object):
    def __init__(self, request):
        self.request = request
        self.payload = self.request.json

    @view_config(header='X-Github-Event:issue_comment')
    def payload_issue_commend(self):
        if self.payload['action'] == 'created':
            check_denied(self.payload)

    @view_config(header='X-Github-Event:issues')
    def payload_issues(self):
        if self.payload['action'] == 'labeled':
            if 'awaiting-review' in self.payload['action']['label']:
                notify_team(payload=self.payload)

        return {'status': 200}

    @view_config(header='X-Github-Event:organization')
    def payload_organization(self):
        if self.payload['action'] == 'member_invited':
            notify_invite(self.payload)
        elif self.payload['action'] == 'member_added':
            notify_added(self.payload)

        return {'status': 200}

    @view_config(header='X-Github-Event:ping')
    def payload_ping(self):
        logging.info('Pinged with id %s', self.payload['hook']['id'])

        return {'status': 200}

def main():
    for issue in repo.get_issues(state='open', labels=[awaiting,]):
        notify_team(issue=issue)

        check_denied(issue=issue)

    logging.info('Configuring webserver')

    config = Configurator()
    config.add_route(CALLBACK_PATH, '/{!s}'.format(CALLBACK_PATH))
    config.scan()

    logging.info('Creating wsgi app')

    app = config.make_wsgi_app()

    logging.info('Starting web server at 0.0.0.0:8000')

    server = make_server('0.0.0.0', 8000, app)
    server.serve_forever()
