# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals

import pygal
from pygal.style import LightGreenStyle

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db.models import F, Sum, Count
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.utils.timezone import now
from django.utils.translation import ugettext_lazy as _, ugettext
from django.views.generic.list import ListView

from src.accounts.models import User
from src.forum.forms import AddTopicForm, AddPostForm
from src.forum.forms import EditPostForm, MoveTopicForm
from src.forum.models import Category, Forum, Topic, Post
from src.forum.settings import POSTS_ON_PAGE, TOPICS_ON_PAGE
from src.utils.views import JsonResponse, object_list


def index(request):
    users_cached = cache.get('users_online', {})
    users_online = users_cached and User.objects.filter(
        id__in=users_cached.keys()) or []
    guests_cached = cache.get('guests_online', {})

    context = {
        'categories': Category.objects.for_user(request.user),
        'users_online': users_online,
        'online_count': len(users_online),
        'guest_count': len(guests_cached),
        'users_count': User.objects.count(),
        'topics_count': Topic.objects.count(),
        'posts_count': Post.objects.count()
    }
    return TemplateResponse(request, 'djforum/index.html', context)


def forum_page(request, pk):
    forum = get_object_or_404(Forum, pk=pk)

    if not forum.has_access(request.user):
        raise Http404

    qs = forum.topics.all()
    extra_context = {
        'forum': forum
    }
    return object_list(request, qs, TOPICS_ON_PAGE,
                       template_name='djforum/forum.html',
                       extra_context=extra_context)


def topic_page(request, pk):
    user = request.user
    topic = get_object_or_404(Topic, pk=pk)

    if not topic.has_access(user):
        raise Http404

    Topic.objects.filter(pk=pk).update(views=F('views') + 1)
    qs = topic.posts.all()
    form = None

    if topic.can_post(user):
        form = AddPostForm(topic, user)

    topic.mark_visited_for(user)

    extra_context = {
        'form': form,
        'forum': topic.forum,
        'topic': topic,
        'has_access': topic.has_access(user)
    }
    return object_list(request, qs, POSTS_ON_PAGE,
                       template_name='djforum/topic.html',
                       extra_context=extra_context)


class UnreadView(ListView):
    paginate_by = TOPICS_ON_PAGE
    template_name = 'djforum/unread_topics.html'

    def get_queryset(self):
        return Topic.objects.unread(user=self.request.user)

    def get_paginator(self, *args, **kwargs):
        paginator = super(UnreadView, self).get_paginator(*args, **kwargs)
        # Fix paginator with raw SQL
        paginator._count = Topic.objects.unread_count(
            user=self.request.user)
        return paginator

unread_topics = login_required(UnreadView.as_view())


@login_required
def mark_read_all(request):
    for forum in Forum.objects.all():
        if forum.has_access(request.user):
            forum.mark_read(request.user)
    return redirect('forum:index')


@login_required
def mark_read_forum(request, pk):
    forum = get_object_or_404(Forum, pk=pk)

    if forum.has_access(request.user):
        forum.mark_read(request.user)

    return redirect(forum)


class MyTopicsView(ListView):
    paginate_by = TOPICS_ON_PAGE
    template_name = 'djforum/my_topics.html'

    def get_queryset(self):
        return Topic.objects.filter(user=self.request.user)

my_topics = login_required(MyTopicsView.as_view())


@login_required
def add_topic(request, pk):
    forum = get_object_or_404(Forum, pk=pk)

    if not forum.has_access(request.user):
        raise Http404

    if not forum.can_post(request.user):
        messages.error(request, _(u'You have no permission to add new topic. Maybe you need to approve your email.'))
        return redirect(forum)

    form = AddTopicForm(forum, request.user, request.POST or None)
    if form.is_valid():
        topic = form.save()
        return redirect(topic)

    context = {
        'form': form,
        'forum': forum
    }

    return TemplateResponse(request, 'djforum/add_topic.html', context)


@login_required
def move_topic(request, pk):
    topic = get_object_or_404(Topic, pk=pk)

    if not topic.can_edit(request.user):
        raise Http404

    form = MoveTopicForm(request.POST or None, instance=topic)

    if form.is_valid():
        form.save()
        return redirect(topic)

    context = {
        'form': form,
        'topic': topic,
        'forum': topic.forum
    }

    return TemplateResponse(request, 'djforum/move_topic.html', context)


@login_required
def add_post(request, pk):
    topic = get_object_or_404(Topic, pk=pk)

    if not topic.has_access(request.user):
        raise Http404

    form = AddPostForm(topic, request.user, request.POST or None)
    if form.is_valid():
        post = form.save()
        return redirect(post)

    context = {
        'form': form,
        'topic': topic,
        'forum': topic.forum
    }
    return TemplateResponse(request, 'djforum/add_post.html', context)


@login_required
def edit_post(request, pk):
    post = get_object_or_404(Post, pk=pk)

    if not post.can_edit(request.user):
        messages.error(request, _('You have no permission edit this post'))
        return redirect(post.topic)

    form = EditPostForm(request.POST or None, instance=post)
    if form.is_valid():
        post = form.save(commit=False)
        post.updated = now()
        post.updated_by = request.user
        post.save()
        return redirect(post)

    context = {
        'form': form,
        'topic': post.topic,
        'forum': post.topic.forum
    }
    return TemplateResponse(request, 'djforum/edit_post.html', context)


@login_required
def subscribe(request, pk):
    topic = get_object_or_404(Topic, pk=pk, user=request.user)
    topic.send_response = True
    topic.save()
    return redirect(topic)


@login_required
def unsubscribe(request, pk):
    topic = get_object_or_404(Topic, pk=pk, user=request.user)
    topic.send_response = False
    topic.save()
    return redirect(topic)


@login_required
def heresy_unheresy_topic(request, pk):
    topic = get_object_or_404(Topic, pk=pk)

    if not topic.can_edit(request.user):
        raise PermissionDenied

    if topic.heresy:
        topic.unmark_heresy()
    else:
        topic.mark_heresy()

    return redirect(topic)


@login_required
def close_open_topic(request, pk):
    topic = get_object_or_404(Topic, pk=pk)

    if not topic.can_edit(request.user):
        raise PermissionDenied

    if topic.closed:
        topic.open()
    else:
        topic.close()

    return redirect(topic)


@login_required
def stick_unstick_topic(request, pk):
    topic = get_object_or_404(Topic, pk=pk)

    if not topic.can_edit(request.user):
        raise PermissionDenied

    if topic.sticky:
        topic.unstick()
    else:
        topic.stick()

    return redirect(topic)


@login_required
def delete_topic(request, pk):
    topic = get_object_or_404(Topic, pk=pk)

    if not topic.can_delete(request.user):
        raise PermissionDenied

    if request.method == 'POST':
        topic.delete()

    return redirect(topic.forum)


@login_required
def delete_post(request, pk):
    post = get_object_or_404(Post, pk=pk)

    if not post.can_delete(request.user):
        raise PermissionDenied

    post.delete()

    try:
        return redirect(Topic.objects.get(pk=post.topic_id))
    except Topic.DoesNotExist:
        return redirect(post.topic.forum)


def vote(request, pk, model):
    user = request.user
    obj = get_object_or_404(model, pk=pk)

    if not user.is_authenticated():
        raise PermissionDenied

    if not obj.has_access(user):
        raise PermissionDenied

    if obj.votes.filter(pk=user.pk).exists():
        obj.votes.remove(user)
        voted = False
    else:
        obj.votes.add(user)
        voted = True

    obj.update_rating()

    return JsonResponse({
        'rating': obj.rating,
        'voted': voted
    })


def statistic(request):
    most_active_users = User.objects.annotate(Count('forum_posts')) \
        .order_by('-forum_posts__count')[:10]
    most_topics_users = User.objects.annotate(Count('forum_topics')) \
        .order_by('-forum_topics__count')[:10]

    context = {
        'active_users_count': User.objects.exclude(forum_posts=None).count(),
        'topics_count': Topic.objects.count(),
        'posts_count': Post.objects.count(),
        'first_post_created': Post.objects.order_by('created')[0].created,
        'views_count': Topic.objects.aggregate(Sum('views'))['views__sum'],
        'most_viewed_topics': Topic.objects.order_by('-views')[:10],
        'most_active_users': most_active_users,
        'most_topics_users': most_topics_users
    }
    return TemplateResponse(request, 'djforum/statistic.html', context)


def posts_per_month_chart(request):
    posts_per_month = Post.objects \
        .extra(select={'year': "EXTRACT(year FROM created)",
               'month': "EXTRACT(month from created)"}) \
        .values('year', 'month').annotate(Count('id')) \
        .order_by('year', 'month')

    chart = pygal.Bar(show_legend=False, style=LightGreenStyle, x_label_rotation=45)
    chart.title = ugettext('Posts per month')
    chart.x_labels = \
        ['%s.%s' % (item['month'], item['year']) for item in posts_per_month]

    data = [{
        'value': item['id__count'],
        'label': '%s.%s' % (item['month'], item['year'])
    } for item in posts_per_month]
    chart.add(ugettext('Posts count'), data)
    content = chart.render()
    return HttpResponse(content, content_type='image/svg+xml')
