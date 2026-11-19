from decimal import Decimal

from django import forms
from django.contrib.auth.forms import AuthenticationForm

from .models import Apartado, Cliente, Pago, Prenda


class StyledMixin:
    """Agrega clases CSS a todos los widgets."""

    def _style(self):
        for name, field in self.fields.items():
            w = field.widget
            if isinstance(w, forms.CheckboxInput):
                w.attrs.setdefault("class", "check")
            elif isinstance(w, forms.Select):
                w.attrs.setdefault("class", "input")
            else:
                w.attrs.setdefault("class", "input")


class LoginForm(StyledMixin, AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Usuario"
        self.fields["password"].label = "Contraseña"
        self._style()


class SeguimientoForm(StyledMixin, forms.Form):
    folio = forms.CharField(label="Folio del apartado", max_length=12, widget=forms.TextInput(attrs={"placeholder": "APT-00001"}))
    telefono = forms.CharField(label="Teléfono (10 dígitos)", max_length=15, widget=forms.TextInput(attrs={"placeholder": "7771234567", "inputmode": "numeric"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class PrendaForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Prenda
        fields = ["codigo", "modelo", "categoria", "talla", "color", "precio", "stock", "stock_minimo", "activa"]
        labels = {"stock_minimo": "Stock mínimo (alerta)", "activa": "Visible en catálogo"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()

    def clean_codigo(self):
        return self.cleaned_data["codigo"].strip().upper()

    def clean_talla(self):
        return self.cleaned_data["talla"].strip().upper()


class ClienteForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ["nombre", "telefono", "email"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class PedidoClienteForm(StyledMixin, forms.Form):
    """Datos de quien hace el pedido (cliente en línea o cliente en mostrador)."""

    nombre = forms.CharField(label="Nombre completo", max_length=120)
    telefono = forms.RegexField(r"^\d{10}$", label="Teléfono (10 dígitos)", error_messages={"invalid": "El teléfono debe tener 10 dígitos."},
                                widget=forms.TextInput(attrs={"inputmode": "numeric", "placeholder": "7771234567"}))
    email = forms.EmailField(label="Correo (opcional)", required=False)
    notas = forms.CharField(label="Notas para la tienda (escuela, empresa, fecha que lo necesitas…)", max_length=255, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class PedidoEnLineaForm(PedidoClienteForm):
    """El cliente elige cómo pagará su anticipo."""

    forma_pago = forms.ChoiceField(label="¿Cómo pagarás tu anticipo?", choices=Apartado.FORMAS_PAGO, initial=Apartado.CAJA,
                                   widget=forms.RadioSelect(attrs={"class": "radio"}))


class PedidoMostradorForm(PedidoClienteForm):
    """Lo mismo, más el anticipo que recibe el vendedor."""

    anticipo = forms.DecimalField(label="Anticipo recibido ($)", min_value=Decimal("0.01"), decimal_places=2, max_digits=12)
    metodo = forms.ChoiceField(label="Forma de pago", choices=Pago.METODOS)


class ConfirmarForm(StyledMixin, forms.Form):
    anticipo = forms.DecimalField(label="Anticipo recibido ($)", min_value=Decimal("0.01"), decimal_places=2, max_digits=12)
    metodo = forms.ChoiceField(label="Forma de pago", choices=Pago.METODOS)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class PagoForm(StyledMixin, forms.Form):
    monto = forms.DecimalField(label="Monto ($)", min_value=Decimal("0.01"), decimal_places=2, max_digits=12)
    metodo = forms.ChoiceField(label="Forma de pago", choices=Pago.METODOS)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class CancelarForm(StyledMixin, forms.Form):
    motivo = forms.CharField(label="Motivo de la cancelación", max_length=255)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class EntradaForm(StyledMixin, forms.Form):
    prenda = forms.ModelChoiceField(queryset=Prenda.objects.none(), label="Prenda")
    cantidad = forms.IntegerField(label="Piezas recibidas", min_value=1)
    proveedor = forms.CharField(label="Proveedor", max_length=120)
    remision = forms.CharField(label="Folio de remisión", max_length=40, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["prenda"].queryset = Prenda.objects.filter(activa=True)
        self._style()
