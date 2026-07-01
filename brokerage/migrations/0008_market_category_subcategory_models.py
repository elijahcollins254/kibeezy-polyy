from django.db import migrations, models
import django.db.models.deletion


def create_default_categories(apps, schema_editor):
    MarketCategory = apps.get_model('brokerage', 'MarketCategory')
    MarketSubcategory = apps.get_model('brokerage', 'MarketSubcategory')
    Market = apps.get_model('brokerage', 'Market')

    category_map = {}
    for name in ['Sports', 'Politics', 'Economy', 'Crypto', 'Technology', 'Environment', 'Geopolitics', 'Other']:
        category_map[name] = MarketCategory.objects.create(name=name, slug=name.lower().replace(' ', '-'))

    for market in Market.objects.all():
        category_name = market.category or 'Other'
        category_obj = category_map.get(category_name, category_map['Other'])
        market.category_obj = category_obj

        if market.subcategory:
            subcat_slug = market.subcategory.lower().replace(' ', '-')
            subcategory_obj, created = MarketSubcategory.objects.get_or_create(
                category=category_obj,
                slug=subcat_slug,
                defaults={'name': market.subcategory}
            )
            market.subcategory_obj = subcategory_obj

        market.save()


def forwards_func(apps, schema_editor):
    create_default_categories(apps, schema_editor)


class Migration(migrations.Migration):

    dependencies = [
        ('brokerage', '0007_market_subcategory'),
    ]

    operations = [
        migrations.CreateModel(
            name='MarketCategory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=64, unique=True)),
                ('slug', models.SlugField(max_length=64, unique=True)),
                ('order', models.IntegerField(default=0, help_text='Use for category sort order')),
            ],
            options={
                'ordering': ['order', 'name'],
                'verbose_name': 'Market Category',
                'verbose_name_plural': 'Market Categories',
            },
        ),
        migrations.CreateModel(
            name='MarketSubcategory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=64)),
                ('slug', models.SlugField(max_length=64)),
                ('order', models.IntegerField(default=0, help_text='Use for subcategory sort order')),
                ('category', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='subcategories', to='brokerage.marketcategory')),
            ],
            options={
                'ordering': ['category', 'order', 'name'],
                'verbose_name': 'Market Subcategory',
                'verbose_name_plural': 'Market Subcategories',
                'unique_together': {('category', 'slug')},
            },
        ),
        migrations.AddField(
            model_name='market',
            name='category_obj',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='markets', to='brokerage.marketcategory'),
        ),
        migrations.AddField(
            model_name='market',
            name='subcategory_obj',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='markets', to='brokerage.marketsubcategory'),
        ),
        migrations.RunPython(forwards_func, migrations.RunPython.noop),
    ]
