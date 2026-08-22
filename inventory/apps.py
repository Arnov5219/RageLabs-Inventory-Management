from django.apps import AppConfig


class InventoryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'inventory'

    def ready(self):
        # Patch django.template.context.BaseContext.__copy__ to avoid Python 3.14 super() copying bug
        from django.template.context import BaseContext
        
        def safe_copy(self):
            duplicate = self.__class__.__new__(self.__class__)
            duplicate.__dict__.update(self.__dict__)
            duplicate.dicts = self.dicts[:]
            return duplicate
            
        BaseContext.__copy__ = safe_copy
