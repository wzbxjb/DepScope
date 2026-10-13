from .app import create_app
from .config import load_settings

app=create_app(load_settings())
