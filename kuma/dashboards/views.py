import datetime
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import permission_required
from django.contrib.auth.models import Group
from django.core.urlresolvers import reverse
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import is_safe_url
from django.views.decorators.http import require_GET, require_POST
import waffle

from kuma.core.utils import paginate
from kuma.wiki.models import Document, Revision, RevisionAkismetSubmission

from .forms import RevisionDashboardForm
from . import PAGE_SIZE


@require_GET
def revisions(request):
    """Dashboard for reviewing revisions"""

    filter_form = RevisionDashboardForm(request.GET)
    page = request.GET.get('page', 1)

    revisions = (Revision.objects.prefetch_related('creator__bans',
                                                   'document',
                                                   'akismet_submissions')
                                 .order_by('-created')
                                 .defer('content'))

    query_kwargs = False
    exclude_kwargs = False

    # We can validate right away because no field is required
    if filter_form.is_valid():
        query_kwargs = {}
        exclude_kwargs = {}
        query_kwargs_map = {
            'user': 'creator__username__istartswith',
            'locale': 'document__locale',
            'topic': 'slug__icontains',
        }

        # Build up a dict of the filter conditions, if any, then apply
        # them all in one go.
        for fieldname, kwarg in query_kwargs_map.items():
            filter_arg = filter_form.cleaned_data[fieldname]
            if filter_arg:
                query_kwargs[kwarg] = filter_arg

        start_date = filter_form.cleaned_data['start_date']
        if start_date:
            end_date = (filter_form.cleaned_data['end_date'] or
                        datetime.datetime.now())
            query_kwargs['created__range'] = [start_date, end_date]

        preceding_period = filter_form.cleaned_data['preceding_period']
        if preceding_period:
            # these are messy but work with timedelta's seconds format,
            # and keep the form and url arguments human readable
            if preceding_period == 'month':
                seconds = 30 * 24 * 60 * 60
            if preceding_period == 'week':
                seconds = 7 * 24 * 60 * 60
            if preceding_period == 'day':
                seconds = 24 * 60 * 60
            if preceding_period == 'hour':
                seconds = 60 * 60
            # use the form date if present, otherwise, offset from now
            end_date = (filter_form.cleaned_data['end_date'] or
                        timezone.now())
            start_date = end_date - datetime.timedelta(seconds=seconds)
            query_kwargs['created__range'] = [start_date, end_date]

        authors_filter = filter_form.cleaned_data['authors']
        if (not filter_form.cleaned_data['user'] != '' and
           authors_filter not in ['', str(RevisionDashboardForm.ALL_AUTHORS)]):

            # The 'Known Authors' group
            group, created = Group.objects.get_or_create(name="Known Authors")
            # If the filter is 'Known Authors', then query for the
            # 'Known Authors' group
            if authors_filter == str(RevisionDashboardForm.KNOWN_AUTHORS):
                query_kwargs['creator__groups__pk'] = group.pk
            # Else query must be 'Unknown Authors', so exclude the
            # 'Known Authors' group
            else:
                exclude_kwargs['creator__groups__pk'] = group.pk

    if query_kwargs or exclude_kwargs:
        revisions = revisions.filter(**query_kwargs).exclude(**exclude_kwargs)

    revisions = paginate(request, revisions, per_page=PAGE_SIZE)

    context = {
        'revisions': revisions,
        'page': page,
        'show_ips': (
            waffle.switch_is_active('store_revision_ips') and
            request.user.is_superuser
        ),
        'show_spam_submission': (
            request.user.is_authenticated() and
            request.user.has_perm('wiki.add_revisionakismetsubmission')
        ),
    }

    # Serve the response HTML conditionally upon request type
    if request.is_ajax():
        template = 'dashboards/includes/revision_dashboard_body.html'
    else:
        template = 'dashboards/revisions.html'
        context['form'] = filter_form

    return render(request, template, context)


@require_GET
def user_lookup(request):
    """Returns partial username matches"""
    userlist = []

    if request.is_ajax():
        user = request.GET.get('user', '')
        if user:
            matches = get_user_model().objects.filter(username__istartswith=user)
            for match in matches:
                userlist.append({'label': match.username})

    data = json.dumps(userlist)
    return HttpResponse(data, content_type='application/json; charset=utf-8')


@require_GET
def topic_lookup(request):
    """Returns partial topic matches"""
    topiclist = []

    if request.is_ajax():
        topic = request.GET.get('topic', '')
        if topic:
            matches = Document.objects.filter(slug__icontains=topic)
            for match in matches:
                topiclist.append({'label': match.slug})

    data = json.dumps(topiclist)
    return HttpResponse(data,
                        content_type='application/json; charset=utf-8')


@require_POST
@permission_required('wiki.add_revisionakismetsubmission')
def submit_akismet_spam(request):
    """Creates SPAM or HAM Akismet record for revision"""
    url = request.POST.get('next')
    if url is None or not is_safe_url(url, request.get_host()):
        url = reverse('dashboards.revisions')
    revision = request.POST.get('revision')
    try:
        revision = Revision.objects.get(pk=revision)
    except Revision.DoesNotExist:
        return redirect(url)

    submission_type = request.POST.get('submit', 'spam')
    RevisionAkismetSubmission.objects.create(
        sender=request.user, revision=revision, type=submission_type)

    return redirect(url)
