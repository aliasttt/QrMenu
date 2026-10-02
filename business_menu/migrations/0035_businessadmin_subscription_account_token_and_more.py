# Generated for Django 5.1.2 on 2026-10-01

import django.db.models.deletion
import uuid
from django.db import migrations, models


def populate_subscription_account_tokens(apps, schema_editor):
    business_admin = apps.get_model("business_menu", "BusinessAdmin")
    for admin in business_admin.objects.filter(subscription_account_token__isnull=True).iterator():
        admin.subscription_account_token = uuid.uuid4()
        admin.save(update_fields=["subscription_account_token"])


class Migration(migrations.Migration):

    dependencies = [
        ('business_menu', '0034_reservation_table'),
    ]

    operations = [
        migrations.AddField(
            model_name='businessadmin',
            name='subscription_account_token',
            field=models.UUIDField(editable=False, help_text='Stable account token supplied to app stores for purchase ownership binding', null=True, unique=True),
        ),
        migrations.RunPython(populate_subscription_account_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='businessadmin',
            name='subscription_account_token',
            field=models.UUIDField(default=uuid.uuid4, editable=False, help_text='Stable account token supplied to app stores for purchase ownership binding', unique=True),
        ),
        migrations.CreateModel(
            name='ProviderSubscription',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('provider', models.CharField(choices=[('apple', 'Apple App Store'), ('stripe', 'Stripe'), ('google', 'Google Play'), ('manual', 'Manual'), ('legacy', 'Legacy')], db_index=True, max_length=16)),
                ('environment', models.CharField(db_index=True, max_length=32)),
                ('external_id', models.CharField(max_length=255)),
                ('latest_transaction_id', models.CharField(blank=True, max_length=255)),
                ('provider_customer_id', models.CharField(blank=True, db_index=True, max_length=255)),
                ('product_id', models.CharField(blank=True, max_length=255)),
                ('status', models.CharField(choices=[('active', 'Active'), ('trialing', 'Store trial'), ('grace_period', 'Grace period'), ('canceled', 'Canceled at period end'), ('expired', 'Expired'), ('revoked', 'Revoked'), ('unpaid', 'Unpaid'), ('unknown', 'Unknown')], db_index=True, default='unknown', max_length=32)),
                ('current_period_end', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('will_renew', models.BooleanField(blank=True, null=True)),
                ('verification_source', models.CharField(choices=[('provider', 'Verified by provider'), ('manual', 'Manual grant'), ('legacy', 'Legacy import')], default='legacy', max_length=16)),
                ('needs_reconciliation', models.BooleanField(db_index=True, default=False)),
                ('last_event_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='provider_subscriptions', to='business_menu.businessadmin')),
            ],
            options={
                'ordering': ['provider', 'environment', 'external_id'],
            },
        ),
        migrations.CreateModel(
            name='ProviderEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('provider', models.CharField(choices=[('apple', 'Apple App Store'), ('stripe', 'Stripe'), ('google', 'Google Play'), ('manual', 'Manual'), ('legacy', 'Legacy')], max_length=16)),
                ('environment', models.CharField(max_length=32)),
                ('external_event_id', models.CharField(max_length=255)),
                ('event_type', models.CharField(blank=True, max_length=64)),
                ('occurred_at', models.DateTimeField(blank=True, null=True)),
                ('processed_at', models.DateTimeField(auto_now_add=True)),
                ('state_applied', models.BooleanField(default=True)),
                ('subscription', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='events', to='business_menu.providersubscription')),
            ],
            options={
                'ordering': ['-processed_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='providersubscription',
            constraint=models.UniqueConstraint(fields=('provider', 'environment', 'external_id'), name='uniq_provider_env_external_subscription'),
        ),
        migrations.AddConstraint(
            model_name='providersubscription',
            constraint=models.UniqueConstraint(condition=models.Q(('latest_transaction_id', ''), _negated=True), fields=('provider', 'environment', 'latest_transaction_id'), name='uniq_provider_env_latest_transaction'),
        ),
        migrations.AddConstraint(
            model_name='providerevent',
            constraint=models.UniqueConstraint(fields=('provider', 'environment', 'external_event_id'), name='uniq_provider_env_external_event'),
        ),
    ]
