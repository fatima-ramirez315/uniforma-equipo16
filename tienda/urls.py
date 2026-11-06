from django.urls import path

from . import views

urlpatterns = [
    path('conexion/', views.conexion, name='conexion'),
]
