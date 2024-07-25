from django.http import HttpResponseRedirect
from django.conf import settings
from django.urls import reverse

class DebugMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if settings.DEBUG and response.status_code == 404:
            return HttpResponseRedirect(reverse('home'))  # Asume que 'home' es el nombre de la URL de tu página de inicio
        return response