def branch_context(request):
    from .models import Branch
    return {
        'all_branches': Branch.objects.filter(active=True)
    }
