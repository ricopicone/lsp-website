from django.contrib import admin

from .models import Election, Nomination, VoterRollEntry

# Ballots and their rankings are deliberately NOT registered: the voter-to-vote
# link is shown to nobody but the voter (task #813). A test pins this.


@admin.register(Election)
class ElectionAdmin(admin.ModelAdmin):
    list_display = ("title", "seats", "nominations_open_at", "voting_close_at")
    readonly_fields = ("count_result", "audit_notes")


@admin.register(Nomination)
class NominationAdmin(admin.ModelAdmin):
    list_display = ("user", "election", "status", "withdrawn_at")
    list_filter = ("election", "status")


@admin.register(VoterRollEntry)
class VoterRollEntryAdmin(admin.ModelAdmin):
    list_display = ("user", "election", "on_roll", "override")
    list_filter = ("election", "on_roll", "override")
