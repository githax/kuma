import urllib
import pytest
from pyquery import PyQuery as pq

from django.contrib.auth.models import Permission

from waffle.models import Flag, Switch

from kuma.core.tests import eq_, ok_
from kuma.core.urlresolvers import reverse
from kuma.core.utils import urlparams
from kuma.dashboards.forms import RevisionDashboardForm
from kuma.spam.constants import SPAM_SUBMISSIONS_FLAG
from kuma.users.tests import UserTestCase
from kuma.users.models import User, UserBan
from kuma.wiki.models import Revision, RevisionAkismetSubmission


@pytest.mark.dashboards
class RevisionsDashTest(UserTestCase):
    fixtures = UserTestCase.fixtures + ['wiki/documents.json']

    def test_main_view(self):
        response = self.client.get(reverse('dashboards.revisions',
                                           locale='en-US'))
        eq_(200, response.status_code)
        ok_('text/html' in response['Content-Type'])
        ok_('dashboards/revisions.html' in
            [template.name for template in response.templates])

    def test_main_view_with_banned_user(self):
        testuser = User.objects.get(username='testuser')
        admin = User.objects.get(username='admin')
        ban = UserBan(user=testuser, by=admin, reason='Testing')
        ban.save()

        self.client.login(username='admin', password='testpass')
        response = self.client.get(reverse('dashboards.revisions',
                                           locale='en-US'))
        eq_(200, response.status_code)

    def test_revision_list(self):
        url = reverse('dashboards.revisions', locale='en-US')
        # We only get revisions when requesting via AJAX.
        response = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        eq_(response.status_code, 200)

        page = pq(response.content)
        revisions = page.find('.dashboard-row')

        eq_(revisions.length, 11)

        # Most recent revision first.
        eq_(int(pq(revisions[0]).attr('data-revision-id')), 30)
        # Second-most-recent revision next.
        eq_(int(pq(revisions[1]).attr('data-revision-id')), 29)
        # Oldest revision last.
        eq_(int(pq(revisions[-1]).attr('data-revision-id')), 19)

    def test_ip_link_on_switch(self):
        url = reverse('dashboards.revisions', locale='en-US')
        response = self.client.get(url)
        eq_(200, response.status_code)

        page = pq(response.content)
        ip_button = page.find('button#show_ips_btn')
        eq_([], ip_button)

        Switch.objects.create(name='store_revision_ips', active=True)
        self.client.login(username='admin', password='testpass')
        url = reverse('dashboards.revisions', locale='en-US')
        response = self.client.get(url)
        eq_(200, response.status_code)

        page = pq(response.content)
        ip_button = page.find('button#show_ips_btn')
        ok_(len(ip_button) > 0)

    def test_spam_submission_buttons(self):
        url = reverse('dashboards.revisions', locale='en-US')
        response = self.client.get(url)
        eq_(200, response.status_code)

        page = pq(response.content)
        spam_table_cell = page.find('td.dashboard-spam')
        eq_(spam_table_cell, [])

        flag = Flag.objects.create(name=SPAM_SUBMISSIONS_FLAG)
        flag.users.add(User.objects.get(username='admin'))
        self.client.login(username='admin', password='testpass')
        url = reverse('dashboards.revisions', locale='en-US')
        response = self.client.get(url)
        eq_(200, response.status_code)

        page = pq(response.content)
        ip_button = page.find('td.dashboard-spam')
        # Revisions available, admin has privileges to see this
        ok_(len(ip_button) > 0)

    def test_submit_akismet_spam_post_required(self):
        url = reverse('dashboards.submit_akismet_spam', locale='en-US')
        response = self.client.get(url)
        eq_(response.status_code, 405, "GET should not be allowed.")

    def test_submit_akismet_spam_valid_response(self):
        urlquery = '?' + urllib.urlencode({'page': 3})
        urlnext = reverse('dashboards.revisions', locale='en-US') + urlquery
        revision = Revision.objects.first()
        data = {
            'revision': revision.pk,
            'submit': u'spam',
            'next': urlnext
        }
        p1 = Permission.objects.get(codename='add_revisionakismetsubmission')
        testuser = User.objects.get(username='testuser')
        testuser.user_permissions.add(p1)
        self.client.login(username='testuser', password='testpass')

        # Response should redirect back to the revisions dash
        urlpost = reverse('dashboards.submit_akismet_spam', locale='en-US')
        response = self.client.post(urlpost, data=data)
        eq_(response.status_code, 302)
        eq_(response.url, 'http://testserver' + urlnext)

        # 1 RevisionAkismetSubmission record should exist for this revision
        ras = RevisionAkismetSubmission.objects.get(revision=revision)
        eq_(ras.type, u'spam')

    def test_submit_akismet_spam_no_permission(self):
        urlnext = reverse('dashboards.revisions', locale='en-US')
        revision = Revision.objects.first()
        data = {
            'revision': revision.pk,
            'submit': u'spam',
            'next': urlnext
        }
        self.client.login(username='testuser', password='testpass')

        # Response should redirect back to the revisions dash
        urlpost = reverse('dashboards.submit_akismet_spam', locale='en-US')
        response = self.client.post(urlpost, data=data)
        eq_(response.status_code, 302)

        # No RevisionAkismetSubmission record should exist, user does not have permission
        ras = RevisionAkismetSubmission.objects.filter(revision=revision)
        eq_(ras.count(), 0)

    def test_submit_akismet_spam_no_url_in_next_variable(self):
        urlnext = reverse('dashboards.revisions')
        revision = Revision.objects.first()
        data = {
            'revision': revision.pk,
            'submit': u'spam',
        }
        self.client.login(username='admin', password='testpass')

        # Response should redirect back to the revisions dash
        urlpost = reverse('dashboards.submit_akismet_spam', locale='en-US')
        response = self.client.post(urlpost, data=data)
        eq_(response.status_code, 302)
        eq_(response.url, 'http://testserver' + urlnext)

        # 1 RevisionAkismetSubmission record should exist for this revision
        ras = RevisionAkismetSubmission.objects.get(revision=revision)
        eq_(ras.type, u'spam')

    def test_submit_akismet_spam_revision_dne(self):
        urlnext = reverse('dashboards.revisions')
        revision_dne = '9999999'
        data = {
            'revision': revision_dne,
            'submit': u'spam',
        }
        self.client.login(username='admin', password='testpass')

        # Response should redirect back to the revisions dash
        urlpost = reverse('dashboards.submit_akismet_spam', locale='en-US')
        response = self.client.post(urlpost, data=data)
        eq_(response.status_code, 302)
        eq_(response.url, 'http://testserver' + urlnext)

        # Zero RevisionAkismetSubmission records should exist for this nonexistent revision
        ras = RevisionAkismetSubmission.objects.filter(revision__pk=revision_dne)
        eq_(ras.count(), 0)

    def test_locale_filter(self):
        url = urlparams(reverse('dashboards.revisions', locale='fr'),
                        locale='fr')
        response = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        eq_(200, response.status_code)

        page = pq(response.content)
        revisions = page.find('.dashboard-row')

        ok_(len(revisions))
        eq_(1, revisions.length)

        ok_('fr' in pq(revisions[0]).find('.locale').html())

    def test_user_lookup(self):
        url = urlparams(reverse('dashboards.user_lookup', locale='en-US'),
                        user='test')
        response = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        eq_(200, response.status_code)

        page = pq(response.content)
        revisions = page.find('.dashboard-row')

        for revision in revisions:
            author = pq(revision).find('.dashboard-author').text()
            ok_('test' in author)
            ok_('admin' not in author)

    def test_creator_filter(self):
        url = urlparams(reverse('dashboards.revisions', locale='en-US'),
                        user='testuser01')
        response = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        eq_(200, response.status_code)

        page = pq(response.content)
        revisions = page.find('.dashboard-row')

        eq_(2, revisions.length)

        for revision in revisions:
            author = pq(revision).find('.dashboard-author').text()
            ok_('testuser01' in author)
            ok_('testuser2' not in author)

    def test_topic_lookup(self):
        url = urlparams(reverse('dashboards.topic_lookup', locale='en-US'),
                        topic='lorem')
        response = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        eq_(200, response.status_code)

        page = pq(response.content)
        revisions = page.find('.dashboard-row')

        for revision in revisions:
            slug = pq(revision).find('.dashboard-title').html()
            ok_('lorem' in slug)
            ok_('article' not in slug)

    def test_topic_filter(self):
        url = urlparams(reverse('dashboards.revisions', locale='en-US'),
                        topic='article-with-revisions')
        response = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        eq_(response.status_code, 200)

        page = pq(response.content)
        revisions = page.find('.dashboard-row')

        eq_(revisions.length, 7)
        for revision in revisions:
            ok_('lorem' not in pq(revision).find('.dashboard-title').html())

    def test_known_authors_lookup(self):
        # Only testuser01 is in the Known Authors group
        url = urlparams(reverse('dashboards.revisions', locale='en-US'),
                        authors=RevisionDashboardForm.KNOWN_AUTHORS)
        response = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        eq_(200, response.status_code)

        page = pq(response.content)
        revisions = page.find('.dashboard-row')

        for revision in revisions:
            author = pq(revision).find('.dashboard-author').html()
            ok_('testuser01' in author)
            ok_('testuser2' not in author)

    def test_known_authors_filter(self):
        # There are a total of 11 revisions
        url = urlparams(reverse('dashboards.revisions', locale='en-US'),
                        authors=RevisionDashboardForm.ALL_AUTHORS)
        response = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        eq_(response.status_code, 200)

        page = pq(response.content)
        revisions = page.find('.dashboard-row')

        eq_(11, revisions.length)

        # Only testuser01 is in the Known Authors group, and has 2 revisions
        url = urlparams(reverse('dashboards.revisions', locale='en-US'),
                        authors=RevisionDashboardForm.KNOWN_AUTHORS)
        response = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        eq_(response.status_code, 200)

        page = pq(response.content)
        revisions = page.find('.dashboard-row')

        eq_(2, revisions.length)

        # Of the 11 revisions, 9 are by users not in the Known Authors group
        url = urlparams(reverse('dashboards.revisions', locale='en-US'),
                        authors=RevisionDashboardForm.UNKNOWN_AUTHORS)
        response = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        eq_(response.status_code, 200)

        page = pq(response.content)
        revisions = page.find('.dashboard-row')

        eq_(9, revisions.length)

    def test_known_authors_filter_ignored_with_username(self):
        """When user filters by username, the Known Authors filter is ignored"""
        # Only testuser01 is in the Known Authors group, and has 2 revisions
        # Filtering by testuser2 should return testuser2's revisions (5 of them)
        # and ignore the "Known Authors" filter
        url = urlparams(reverse('dashboards.revisions', locale='en-US'),
                        user='testuser2', authors=RevisionDashboardForm.KNOWN_AUTHORS)
        response = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        eq_(response.status_code, 200)

        page = pq(response.content)
        revisions = page.find('.dashboard-row')

        eq_(5, revisions.length)
