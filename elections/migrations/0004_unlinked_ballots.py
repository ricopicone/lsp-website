# Hand-written: a ballot loses its voter and its timestamps and gains a UUID
# key (the Board's decision, 2026-10-14). An integer key can't be altered to a
# UUID in place on Postgres, so the two ballot tables are dropped and made
# again. No election had ever opened voting on any database when this ran,
# so there are no ballots to carry across.

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('elections', '0003_emailed_nominations'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.DeleteModel(name='BallotRanking'),
        migrations.DeleteModel(name='Ballot'),
        migrations.CreateModel(
            name='Ballot',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('election', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='ballots', to='elections.election')),
            ],
        ),
        migrations.CreateModel(
            name='BallotRanking',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rank', models.PositiveSmallIntegerField()),
                ('ballot', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='rankings', to='elections.ballot')),
                ('nomination', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='elections.nomination')),
            ],
            options={
                'constraints': [
                    models.UniqueConstraint(fields=('ballot', 'rank'), name='ballot_rank_unique'),
                    models.UniqueConstraint(fields=('ballot', 'nomination'), name='ballot_candidate_unique'),
                ],
            },
        ),
        migrations.CreateModel(
            name='VoteRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('election', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='vote_records', to='elections.election')),
                ('voter', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='election_votes', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'constraints': [
                    models.UniqueConstraint(fields=('election', 'voter'), name='election_one_vote_per_voter'),
                ],
            },
        ),
    ]
