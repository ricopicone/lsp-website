"""Payment.Status gains ABANDONED (task #474) — a checkout the member never
finished, distinct from a declined card. The Charge.effective_date help_text is
along for the ride (text-only drift from task #473's category-scoped sweep)."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0022_balancereminder'),
    ]

    operations = [
        migrations.AlterField(
            model_name='charge',
            name='effective_date',
            field=models.DateField(help_text='Orders the oldest-first coverage sweep (within a category, then across) — AY start for dues/tuition, settle date for registrations.'),
        ),
        migrations.AlterField(
            model_name='payment',
            name='status',
            field=models.CharField(choices=[('pending', 'Pending'), ('succeeded', 'Succeeded'), ('failed', 'Failed'), ('refunded', 'Refunded'), ('abandoned', 'Abandoned')], default='pending', max_length=20),
        ),
    ]
