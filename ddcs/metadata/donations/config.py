# Participants (``Participant.external_id``) known to be test cases. Their
# donations are left out when the donation infos are rebuilt from the stored
# donations (``record_donated_videos`` command). Donations coming in are not
# checked: new ones always arrive under other IDs.
EXCLUDED_PARTICIPANT_IDS = frozenset(
    {
        "yKzBB1S5DbURLAxtlleBLzti",
        "hyZC1bv3SulXEqcVCBuZ9sJF",
        "Ry5qgzXfiEzacrlIAr0u6dyt",
        "QEzW5jZRB9N5SR4tNvqrl3Qf",
        "dwZCB1xmuVPkcCi3kVsqD6DA",
        "LtbPOltW53hZIUgVgjx46Pk0",
        "FbN5XdlrOZKo6tMk5tRVwl08",
        "26r3yOhXvaPd2dPQS1BdZPVv",
        "azdnmeNSOd8Sh2frMTHswvIN",
        "rjJGSJ6nCytvd0mlgQAW74Kw",
        "SRiC7hJBa8H5YaxeMWDxNqQ2",
        "E0Bfv3wtZnZvu3VON2OB4cmu",
        "yrYplT2M6u4Sl8UMURQ8xxrw",
        "ouPbO0aseGTNnOmY5HFoxgox",
        "9wdbSOvlq0fMJ5HrmhrX9Cnf",
    }
)
