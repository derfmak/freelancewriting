from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib import messages
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Q, Count, Avg, F, Sum
from django.contrib.postgres.search import SearchVector, SearchQuery, SearchRank
from django.utils import timezone
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework import status
from decimal import Decimal
from apps.accounts.models import User
from apps.orders.models import Order, OrderHistory
from apps.orders.serializers import OrderListSerializer
from apps.admin_portal.models import Blog, Sample
from apps.messaging.models import Conversation
import hashlib
import json
from datetime import timedelta


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def home(request):
    return render(request, 'public/home.html')


@api_view(['GET'])
def about_stats(request):
    cache_key = 'about_page_stats'
    stats = cache.get(cache_key)
    
    if stats is None:
        total_orders = Order.objects.filter(status='completed').count()
        total_clients = User.objects.filter(role='client', is_active=True).count()
        total_writers = User.objects.filter(role='writer', is_active=True).count()
        
        ratings = Order.objects.filter(rating__isnull=False).aggregate(Avg('rating'))
        avg_rating = ratings['rating__avg'] or 4.9
        satisfaction = min(99, int((avg_rating / 5) * 100))
        
        stats = {
            'orders': total_orders,
            'clients': total_clients,
            'writers': total_writers,
            'satisfaction_rate': satisfaction
        }
        
        cache.set(cache_key, stats, 300)
    
    return Response(stats)


def about(request):
    return render(request, 'public/about.html')


def how_it_works(request):
    return render(request, 'public/how-it-works.html')


def services(request):
    return render(request, 'public/services.html')


def pricing(request):
    return render(request, 'public/pricing.html')


def contact(request):
    return render(request, 'public/contact.html')


def terms(request):
    return render(request, 'public/terms.html')


def privacy(request):
    return render(request, 'public/privacy.html')


def refund_policy(request):
    return render(request, 'public/refund-policy.html')


def faq(request):
    return render(request, 'public/faq.html')


def place_order(request):
    return render(request, 'public/place-order.html')


def samples(request):
    samples = Sample.objects.filter(is_active=True).order_by('-created_at')
    context = {
        'samples': samples,
    }
    return render(request, 'public/samples.html', context)


def download_sample(request, sample_id):
    ip = get_client_ip(request)
    rate_key = f"download_rate:{ip}"
    
    download_data = cache.get(rate_key, {'count': 0, 'reset_at': None})
    current_time = timezone.now().timestamp()
    
    if download_data.get('reset_at') and current_time > download_data['reset_at']:
        download_data = {'count': 0, 'reset_at': None}
    
    if download_data['count'] >= 2:
        remaining_time = int(download_data['reset_at'] - current_time)
        minutes = remaining_time // 60
        seconds = remaining_time % 60
        
        if minutes > 0:
            wait_message = f"Please wait {minutes} minute{'s' if minutes > 1 else ''} and {seconds} second{'s' if seconds != 1 else ''} before trying again."
        else:
            wait_message = f"Please wait {seconds} second{'s' if seconds != 1 else ''} before trying again."
        
        return JsonResponse({
            'success': False,
            'error': 'rate_limited',
            'message': 'You have reached the download limit.',
            'details': f'You can download up to 2 samples every 10 minutes. {wait_message}',
            'retry_after': remaining_time
        }, status=429)
    
    sample = get_object_or_404(Sample, id=sample_id, is_active=True)
    
    sample.downloads = F('downloads') + 1
    sample.save(update_fields=['downloads'])
    sample.refresh_from_db()
    
    if download_data['count'] == 0:
        download_data['reset_at'] = current_time + 600
    download_data['count'] += 1
    cache.set(rate_key, download_data, 600)
    
    return JsonResponse({
        'success': True,
        'file_url': sample.file.url,
        'downloads': sample.downloads,
        'remaining': 2 - download_data['count'],
        'message': 'Download started successfully.'
    })


def guarantees(request):
    return render(request, 'public/guarantees.html')


def testimonials(request):
    return render(request, 'public/testimonials.html')


def blog(request):
    search_query = request.GET.get('search', '')
    posts = Blog.objects.filter(published_at__lte=timezone.now()).order_by('-published_at')
    
    if search_query:
        posts = posts.filter(
            Q(title__icontains=search_query) | 
            Q(content__icontains=search_query) |
            Q(excerpt__icontains=search_query)
        )
    
    paginator = Paginator(posts, 9)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    recent_posts = Blog.objects.filter(published_at__lte=timezone.now()).order_by('-published_at')[:5]
    
    context = {
        'posts': page_obj,
        'page_obj': page_obj,
        'recent_posts': recent_posts,
        'search_query': search_query,
    }
    return render(request, 'public/blog.html', context)


def blog_detail(request, slug):
    blog_post = get_object_or_404(Blog, slug=slug, published_at__lte=timezone.now())
    
    blog_post.views = F('views') + 1
    blog_post.save(update_fields=['views'])
    blog_post.refresh_from_db()
    
    related_posts = Blog.objects.filter(
        published_at__lte=timezone.now()
    ).exclude(id=blog_post.id).order_by('-published_at')[:3]
    
    context = {
        'blog_post': blog_post,
        'related_posts': related_posts,
    }
    return render(request, 'public/blog.html', context)


@api_view(['GET'])
def blog_search_suggestions(request):
    query = request.GET.get('q', '').strip()
    
    if len(query) < 2:
        return Response({'suggestions': []})
    
    posts = Blog.objects.filter(
        published_at__lte=timezone.now()
    ).filter(
        Q(title__icontains=query) |
        Q(content__icontains=query) |
        Q(excerpt__icontains=query)
    ).values('id', 'title', 'slug', 'excerpt')[:10]
    
    suggestions = []
    for post in posts:
        excerpt = post['excerpt']
        if len(excerpt) > 120:
            excerpt = excerpt[:120] + '...'
        suggestions.append({
            'id': post['id'],
            'title': post['title'],
            'slug': post['slug'],
            'excerpt': excerpt
        })
    
    return Response({'suggestions': suggestions})


@require_POST
@csrf_exempt
def blog_share(request, slug):
    ip = get_client_ip(request)
    rate_key = f"share_rate:{slug}:{ip}"
    
    share_data = cache.get(rate_key, {'count': 0, 'reset_at': None})
    current_time = timezone.now().timestamp()
    
    if share_data.get('reset_at') and current_time > share_data['reset_at']:
        share_data = {'count': 0, 'reset_at': None}
    
    if share_data['count'] >= 5:
        return JsonResponse({
            'success': False,
            'error': 'rate_limited',
            'message': 'Too many shares. Please wait before sharing again.'
        }, status=429)
    
    try:
        blog_post = get_object_or_404(Blog, slug=slug, published_at__lte=timezone.now())
        
        blog_post.shares = F('shares') + 1
        blog_post.save(update_fields=['shares'])
        blog_post.refresh_from_db()
        
        if share_data['count'] == 0:
            share_data['reset_at'] = current_time + 60
        share_data['count'] += 1
        cache.set(rate_key, share_data, 60)
        
        return JsonResponse({
            'success': True,
            'shares': blog_post.shares,
            'message': 'Share counted successfully.'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@require_POST
@csrf_exempt
def contact_message(request):
    ip = get_client_ip(request)
    rate_key = f"contact_rate:{ip}"
    
    contact_data = cache.get(rate_key, {'count': 0, 'reset_at': None})
    current_time = timezone.now().timestamp()
    
    if contact_data.get('reset_at') and current_time > contact_data['reset_at']:
        contact_data = {'count': 0, 'reset_at': None}
    
    if contact_data['count'] >= 3:
        return JsonResponse({
            'success': False,
            'error': 'rate_limited',
            'message': 'Too many messages. Please wait before sending another message.'
        }, status=429)
    
    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        email = data.get('email', '').strip()
        subject = data.get('subject', '').strip()
        message = data.get('message', '').strip()
        
        if not all([name, email, subject, message]):
            return JsonResponse({
                'success': False,
                'error': 'All fields are required.'
            }, status=400)
        
        if len(message) < 10:
            return JsonResponse({
                'success': False,
                'error': 'Message must be at least 10 characters.'
            }, status=400)
        
        cache_key = f"contact_message:{hashlib.md5(email.encode()).hexdigest()}"
        if cache.get(cache_key):
            return JsonResponse({
                'success': False,
                'error': 'You have already sent a message recently. Please wait.'
            }, status=429)
        
        cache.set(cache_key, True, 600)
        
        if contact_data['count'] == 0:
            contact_data['reset_at'] = current_time + 300
        contact_data['count'] += 1
        cache.set(rate_key, contact_data, 300)
        
        return JsonResponse({
            'success': True,
            'message': 'Your message has been sent. We\'ll respond within 2 hours.'
        })
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid request format.'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': 'An error occurred. Please try again.'
        }, status=500)


def forgot_password(request):
    return render(request, 'public/forgot-password.html')


def reset_password(request, token=None):
    return render(request, 'public/reset-password.html', {'token': token})


def login_view(request):
    return render(request, 'public/login.html')


def register_view(request):
    return render(request, 'public/register.html')


@login_required
def dashboard_redirect(request):
    if request.user.role == 'admin':
        return redirect('admin-dashboard')
    elif request.user.role == 'client':
        return redirect('client-dashboard')
    return redirect('home')


@login_required
def client_dashboard(request):
    if request.user.role != 'client':
        return render(request, 'access_denied.html')
    return render(request, 'client/dashboard.html')


@login_required
def client_orders(request):
    if request.user.role != 'client':
        return render(request, 'access_denied.html')
    return render(request, 'client/orders.html')


@login_required
def client_new_order(request):
    if request.user.role != 'client':
        return render(request, 'access_denied.html')
    return render(request, 'client/new-order.html')


@login_required
def client_order_detail(request, order_id):
    if request.user.role != 'client':
        return render(request, 'access_denied.html')
    return render(request, 'client/order-detail.html', {'order_id': order_id})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def client_order_detail_data(request, order_id):
    try:
        from apps.orders.serializers import OrderSerializer
        order = get_object_or_404(Order, id=order_id, client=request.user)
        serializer = OrderSerializer(order, context={'request': request})
        return Response(serializer.data)
    except Order.DoesNotExist:
        return Response({'error': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@login_required
def client_wallet(request):
    if request.user.role != 'client':
        return render(request, 'access_denied.html')
    return render(request, 'client/wallet.html')


@login_required
def client_messages(request):
    if request.user.role == 'client':
        return render(request, 'client/messages.html')
    elif request.user.role == 'admin':
        return render(request, 'admin/messages.html')
    return render(request, 'access_denied.html')


@login_required
def client_order_messages(request, order_id):
    if request.user.role != 'client':
        return render(request, 'access_denied.html')
    return render(request, 'client/messages.html', {'order_id': order_id})


@login_required
def client_announcements(request):
    if request.user.role != 'client':
        return render(request, 'access_denied.html')
    return render(request, 'client/announcements.html')


@login_required
def client_profile(request):
    if request.user.role != 'client':
        return render(request, 'access_denied.html')
    return render(request, 'client/profile.html')


@login_required
def client_profile_edit(request):
    if request.user.role != 'client':
        return render(request, 'access_denied.html')
    return render(request, 'client/profile-edit.html')


@login_required
def client_settings(request):
    if request.user.role != 'client':
        return render(request, 'access_denied.html')
    return render(request, 'client/settings.html')


@login_required
def admin_profile(request):
    if request.user.role != 'admin':
        return render(request, 'access_denied.html')
    return render(request, 'admin/profile.html')


@login_required
def admin_settings(request):
    if request.user.role != 'admin':
        return render(request, 'access_denied.html')
    return render(request, 'admin/settings.html')


@login_required
def client_notifications(request):
    if request.user.role != 'client':
        return render(request, 'access_denied.html')
    return render(request, 'client/notifications.html')


@login_required
def admin_notifications(request):
    if request.user.role != 'admin':
        return render(request, 'access_denied.html')
    return render(request, 'admin/notifications.html')


@login_required
def notifications(request):
    if request.user.role == 'client':
        return render(request, 'client/notifications.html')
    elif request.user.role == 'admin':
        return render(request, 'admin/notifications.html')
    return render(request, 'access_denied.html')


@login_required
def admin_dashboard(request):
    if request.user.role != 'admin':
        return render(request, 'access_denied.html')
    return render(request, 'admin/dashboard.html')


@login_required
def admin_orders(request):
    if request.user.role != 'admin':
        return render(request, 'access_denied.html')
    return render(request, 'admin/orders.html')


@login_required
def admin_users(request):
    if request.user.role != 'admin':
        return render(request, 'access_denied.html')
    return render(request, 'admin/users.html')


@login_required
def admin_finances(request):
    if request.user.role != 'admin':
        return render(request, 'access_denied.html')
    return render(request, 'admin/finances.html')


@login_required
def admin_refunds(request):
    if request.user.role != 'admin':
        return render(request, 'access_denied.html')
    return render(request, 'admin/refunds.html')


@login_required
def admin_blog(request):
    if request.user.role != 'admin':
        return render(request, 'access_denied.html')
    
    search_query = request.GET.get('search', '')
    posts = Blog.objects.all().order_by('-published_at')
    
    if search_query:
        posts = posts.filter(
            Q(title__icontains=search_query) |
            Q(content__icontains=search_query) |
            Q(excerpt__icontains=search_query)
        )
    
    context = {
        'posts': posts,
        'search_query': search_query,
        'now': timezone.now(),
    }
    return render(request, 'admin/blog.html', context)


@login_required
def admin_create_blog(request):
    if request.user.role != 'admin':
        return render(request, 'access_denied.html')
    
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        slug = request.POST.get('slug', '').strip()
        excerpt = request.POST.get('excerpt', '').strip()
        content = request.POST.get('content', '').strip()
        published_at = request.POST.get('published_at')
        
        errors = []
        
        if not title:
            errors.append('Title is required.')
        elif len(title) < 3:
            errors.append('Title must be at least 3 characters.')
        
        if not content:
            errors.append('Content is required.')
        elif len(content) < 10:
            errors.append('Content must be at least 10 characters.')
        
        if not excerpt:
            errors.append('Excerpt is required.')
        elif len(excerpt) > 300:
            errors.append('Excerpt must be less than 300 characters.')
        elif len(excerpt) < 10:
            errors.append('Excerpt must be at least 10 characters.')
        
        if slug:
            slug = slug.lower().replace(' ', '-')
            if not slug[0].isalpha() and slug[0] != '-':
                errors.append('Slug must start with a letter.')
            if ' ' in slug:
                errors.append('Slug cannot contain spaces.')
            if Blog.objects.filter(slug=slug).exists():
                errors.append('A blog post with this slug already exists.')
        else:
            from django.utils.text import slugify
            slug = slugify(title)
            if Blog.objects.filter(slug=slug).exists():
                slug = f"{slug}-{int(timezone.now().timestamp())}"
        
        if errors:
            for error in errors:
                messages.error(request, error)
            context = {
                'title': title,
                'slug': slug,
                'excerpt': excerpt,
                'content': content,
                'published_at': published_at,
                'errors': errors
            }
            return render(request, 'admin/create-blog.html', context)
        
        try:
            if published_at:
                from datetime import datetime
                published_at = datetime.strptime(published_at, '%Y-%m-%dT%H:%M')
            else:
                published_at = timezone.now()
            
            blog_post = Blog.objects.create(
                title=title,
                slug=slug,
                excerpt=excerpt,
                content=content,
                published_at=published_at,
                created_by=request.user
            )
            
            messages.success(request, f'Blog post "{title}" created successfully.')
            return redirect('admin-blog')
            
        except Exception as e:
            messages.error(request, f'Failed to create blog post: {str(e)}')
            context = {
                'title': title,
                'slug': slug,
                'excerpt': excerpt,
                'content': content,
                'published_at': published_at,
                'errors': [str(e)]
            }
            return render(request, 'admin/create-blog.html', context)
    
    context = {}
    return render(request, 'admin/create-blog.html', context)


@login_required
def admin_edit_blog(request, blog_id):
    if request.user.role != 'admin':
        return render(request, 'access_denied.html')
    
    blog_post = get_object_or_404(Blog, id=blog_id)
    
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        slug = request.POST.get('slug', '').strip()
        excerpt = request.POST.get('excerpt', '').strip()
        content = request.POST.get('content', '').strip()
        published_at = request.POST.get('published_at')
        
        errors = []
        
        if not title:
            errors.append('Title is required.')
        elif len(title) < 3:
            errors.append('Title must be at least 3 characters.')
        
        if not content:
            errors.append('Content is required.')
        elif len(content) < 10:
            errors.append('Content must be at least 10 characters.')
        
        if not excerpt:
            errors.append('Excerpt is required.')
        elif len(excerpt) > 300:
            errors.append('Excerpt must be less than 300 characters.')
        elif len(excerpt) < 10:
            errors.append('Excerpt must be at least 10 characters.')
        
        if slug:
            slug = slug.lower().replace(' ', '-')
            if not slug[0].isalpha() and slug[0] != '-':
                errors.append('Slug must start with a letter.')
            if ' ' in slug:
                errors.append('Slug cannot contain spaces.')
            if Blog.objects.filter(slug=slug).exclude(id=blog_id).exists():
                errors.append('A blog post with this slug already exists.')
        else:
            from django.utils.text import slugify
            slug = slugify(title)
            if Blog.objects.filter(slug=slug).exclude(id=blog_id).exists():
                slug = f"{slug}-{int(timezone.now().timestamp())}"
        
        if errors:
            for error in errors:
                messages.error(request, error)
            context = {
                'blog_post': blog_post,
                'title': title,
                'slug': slug,
                'excerpt': excerpt,
                'content': content,
                'published_at': published_at,
                'errors': errors
            }
            return render(request, 'admin/edit-blog.html', context)
        
        try:
            if published_at:
                from datetime import datetime
                published_at = datetime.strptime(published_at, '%Y-%m-%dT%H:%M')
            else:
                published_at = blog_post.published_at
            
            blog_post.title = title
            blog_post.slug = slug
            blog_post.excerpt = excerpt
            blog_post.content = content
            blog_post.published_at = published_at
            blog_post.save()
            
            messages.success(request, f'Blog post "{title}" updated successfully.')
            return redirect('admin-blog')
            
        except Exception as e:
            messages.error(request, f'Failed to update blog post: {str(e)}')
            context = {
                'blog_post': blog_post,
                'title': title,
                'slug': slug,
                'excerpt': excerpt,
                'content': content,
                'published_at': published_at,
                'errors': [str(e)]
            }
            return render(request, 'admin/edit-blog.html', context)
    
    context = {
        'blog_post': blog_post,
        'title': blog_post.title,
        'slug': blog_post.slug,
        'excerpt': blog_post.excerpt,
        'content': blog_post.content,
        'published_at': blog_post.published_at.strftime('%Y-%m-%dT%H:%M') if blog_post.published_at else '',
    }
    return render(request, 'admin/edit-blog.html', context)


@login_required
def admin_toggle_blog_status(request, blog_id):
    if request.user.role != 'admin':
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=403)
    
    try:
        blog_post = get_object_or_404(Blog, id=blog_id)
        
        if blog_post.published_at <= timezone.now():
            blog_post.published_at = timezone.now() + timedelta(days=365*10)
            status_text = 'deactivated'
            is_active = False
        else:
            blog_post.published_at = timezone.now()
            status_text = 'activated'
            is_active = True
        
        blog_post.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Blog post "{blog_post.title}" {status_text}.',
            'status': status_text,
            'is_active': is_active,
            'status_display': 'Published' if is_active else 'Draft'
        })
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@login_required
def admin_delete_blog_ajax(request, blog_id):
    if request.user.role != 'admin':
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=403)
    
    try:
        blog_post = get_object_or_404(Blog, id=blog_id)
        title = blog_post.title
        blog_post.delete()
        
        return JsonResponse({
            'success': True,
            'message': f'Blog post "{title}" deleted successfully.'
        })
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@api_view(['GET'])
def admin_blog_search_suggestions(request):
    if request.user.role != 'admin':
        return Response({'suggestions': []}, status=403)
    
    query = request.GET.get('q', '').strip()
    
    if len(query) < 2:
        return Response({'suggestions': []})
    
    posts = Blog.objects.filter(
        Q(title__icontains=query) |
        Q(content__icontains=query) |
        Q(excerpt__icontains=query)
    ).values('id', 'title', 'excerpt')[:10]
    
    suggestions = []
    for post in posts:
        excerpt = post['excerpt']
        if len(excerpt) > 120:
            excerpt = excerpt[:120] + '...'
        suggestions.append({
            'id': post['id'],
            'title': post['title'],
            'excerpt': excerpt
        })
    
    return Response({'suggestions': suggestions})


@api_view(['GET'])
def admin_blog_detail(request, blog_id):
    if request.user.role != 'admin':
        return Response({'success': False, 'message': 'Unauthorized'}, status=403)
    
    try:
        post = get_object_or_404(Blog, id=blog_id)
        
        return Response({
            'success': True,
            'post': {
                'id': str(post.id),
                'title': post.title,
                'slug': post.slug,
                'excerpt': post.excerpt,
                'content': post.content,
                'views': post.views,
                'is_published': post.published_at <= timezone.now(),
                'published_at': post.published_at.strftime('%B %d, %Y at %I:%M %p'),
                'reading_time': post.get_reading_time(),
                'author': post.created_by.get_full_name() if post.created_by else 'Unknown'
            }
        })
    except Exception as e:
        return Response({'success': False, 'message': str(e)}, status=500)


@login_required
def admin_samples(request):
    if request.user.role != 'admin':
        return render(request, 'access_denied.html')
    
    samples = Sample.objects.all().order_by('-created_at')
    
    if request.method == 'POST':
        title = request.POST.get('title')
        description = request.POST.get('description')
        file = request.FILES.get('file')
        is_active = request.POST.get('is_active') == 'true'
        
        if file and title:
            sample = Sample.objects.create(
                title=title,
                description=description,
                file=file,
                file_name=file.name,
                file_size=file.size,
                file_type=file.content_type,
                uploaded_by=request.user,
                is_active=is_active
            )
            messages.success(request, f'Sample "{title}" uploaded successfully.')
            return redirect('admin-samples')
        else:
            messages.error(request, 'Title and file are required.')
    
    context = {
        'samples': samples,
    }
    return render(request, 'admin/samples.html', context)


@login_required
def admin_toggle_sample(request, sample_id):
    if request.user.role != 'admin':
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=403)
    
    try:
        sample = get_object_or_404(Sample, id=sample_id)
        sample.is_active = not sample.is_active
        sample.save()
        
        status = 'activated' if sample.is_active else 'deactivated'
        return JsonResponse({'success': True, 'message': f'Sample "{sample.title}" {status}.'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@login_required
def admin_delete_sample(request, sample_id):
    if request.user.role != 'admin':
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=403)
    
    try:
        sample = get_object_or_404(Sample, id=sample_id)
        title = sample.title
        sample.delete()
        return JsonResponse({'success': True, 'message': f'Sample "{title}" deleted.'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@login_required
def admin_content(request):
    if request.user.role != 'admin':
        return render(request, 'access_denied.html')
    return render(request, 'admin/content.html')


@login_required
def admin_logs(request):
    if request.user.role != 'admin':
        return render(request, 'access_denied.html')
    return render(request, 'admin/logs.html')


@login_required
def admin_messages(request):
    if request.user.role != 'admin':
        return render(request, 'access_denied.html')
    return render(request, 'admin/messages.html')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def client_counts(request):
    try:
        orders = Order.objects.filter(client=request.user)
        
        active_orders = orders.filter(
            status__in=['request', 'in_progress', 'awaiting_approval']
        ).count()
        
        completed_orders = orders.filter(status='completed').count()
        total_orders = orders.count()
        cancelled_orders = orders.filter(status='cancelled').count()
        declined_orders = orders.filter(status='declined').count()
        
        unread_messages = 0
        try:
            conversations = Conversation.objects.filter(client=request.user)
            for conv in conversations:
                unread_messages += conv.get_unread_count(request.user)
        except Exception:
            pass
        
        return Response({
            'active_orders': active_orders,
            'completed_orders': completed_orders,
            'total_orders': total_orders,
            'cancelled_orders': cancelled_orders,
            'declined_orders': declined_orders,
            'unread_messages': unread_messages,
        })
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def admin_counts(request):
    try:
        total_users = User.objects.count()
        total_clients = User.objects.filter(role='client').count()
        total_writers = User.objects.filter(role='writer').count()
        
        total_orders = Order.objects.count()
        active_orders = Order.objects.filter(
            status__in=['request', 'in_progress', 'awaiting_approval']
        ).count()
        pending_orders = Order.objects.filter(status='request').count()
        in_progress_orders = Order.objects.filter(status='in_progress').count()
        awaiting_orders = Order.objects.filter(status='awaiting_approval').count()
        completed_orders = Order.objects.filter(status='completed').count()
        cancelled_orders = Order.objects.filter(status='cancelled').count()
        declined_orders = Order.objects.filter(status='declined').count()
        
        from apps.payments.models import Transaction
        total_revenue = Transaction.objects.filter(
            type='payout',
            status='completed'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        pending_payouts = Transaction.objects.filter(
            type='payout',
            status='pending'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        avg_rating = Order.objects.filter(rating__isnull=False).aggregate(
            avg=Avg('rating')
        )['avg'] or 0
        
        unread_messages = 0
        try:
            conversations = Conversation.objects.filter(admin=request.user)
            for conv in conversations:
                unread_messages += conv.get_unread_count(request.user)
        except Exception:
            pass
        
        return Response({
            'total_users': total_users,
            'total_clients': total_clients,
            'total_writers': total_writers,
            'total_orders': total_orders,
            'active_orders': active_orders,
            'pending_orders': pending_orders,
            'in_progress_orders': in_progress_orders,
            'awaiting_orders': awaiting_orders,
            'completed_orders': completed_orders,
            'cancelled_orders': cancelled_orders,
            'declined_orders': declined_orders,
            'total_revenue': float(total_revenue),
            'pending_payouts': float(pending_payouts),
            'average_rating': float(avg_rating),
            'unread_messages': unread_messages,
        })
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def client_wallet_data(request):
    try:
        wallet = request.user.wallet
        return Response({
            'balance': float(wallet.balance),
            'held_balance': float(wallet.held_balance),
            'available_balance': float(wallet.available_balance),
            'total_deposited': float(wallet.total_deposited),
            'total_spent': float(wallet.total_spent),
            'total_refunded': float(wallet.total_refunded),
            'total_withdrawn': float(wallet.total_withdrawn),
            'currency': wallet.currency
        })
    except Exception:
        return Response({
            'balance': 0.00,
            'held_balance': 0.00,
            'available_balance': 0.00,
            'total_deposited': 0.00,
            'total_spent': 0.00,
            'total_refunded': 0.00,
            'total_withdrawn': 0.00,
            'currency': 'USD'
        })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def client_orders_data(request):
    try:
        status_filter = request.GET.get('status')
        search = request.GET.get('search')
        limit = request.GET.get('limit')
        
        orders = Order.objects.filter(client=request.user).order_by('-created_at')
        
        if status_filter:
            status_list = status_filter.split(',')
            orders = orders.filter(status__in=status_list)
        
        if search:
            orders = orders.filter(
                Q(order_number__icontains=search) |
                Q(topic__icontains=search) |
                Q(subject__icontains=search)
            )
        
        total = orders.count()
        
        if limit:
            try:
                limit_int = int(limit)
                orders = orders[:limit_int]
            except ValueError:
                pass
        
        serializer = OrderListSerializer(orders, many=True, context={'request': request})
        
        return Response({
            'results': serializer.data,
            'total': total,
            'page': 1,
            'page_size': len(serializer.data)
        })
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)