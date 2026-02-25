# cadrius/middleware.py
class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            request.tenant = request.user.organization
        else:
            request.tenant = None
        
        return self.get_response(request)