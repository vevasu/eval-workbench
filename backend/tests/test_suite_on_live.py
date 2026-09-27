import json

STORY = ("In a dimly lit room, Sarah proposed a horror story theme for their dinner party. \u201cHow about a haunted toaster?\u201d "
         "Everyone laughed. They joked about toasts burning\u2014until the toaster began to smoke. \u201cIs that supposed to happen?\u201d "
         "someone asked nervously. They bravely approached, when the toaster popped out a perfectly golden slice. Screams "
         "erupted as they realized the horror was just messy cleaning!")  # a real answer from the story app, 400+ characters
APP_RULE = {"type": "not_contains", "values": ["…"], "category": "Incomplete answer"}  # what the story app sends itself


def test_a_live_prompt_is_checked_by_the_test_case_it_matches(client, admin):
    client.post("/admin/projects", headers=admin, json={"name": "Story team", "id": "story-team"})
    auth = {"Authorization": "Bearer " + client.post("/admin/projects/story-team/keys", headers=admin, json={"name": "t"}).json()["key"]}

    def prompt(text):
        return client.post("/ingest", headers=auth, json={"suiteId": "story-live", "input": text, "actual": STORY,
                                                          "checks": [APP_RULE]}).json()["result"]

    # Before the suite has a test for it, the story passes the app's own rule.
    assert prompt("Suggest a horror story (genre: comedy)")["verdict"] == "Pass"

    # Import a suite with a test case for this prompt: the same prompt now fails, and says which test case checked it.
    suite = {"name": "Story generator", "cases": [{"input": "Suggest a horror story (genre: comedy)",
                                                   "expected": "Points out the conflict and asks which the person wants.",
                                                   "checks": [{"type": "max_length", "max": 300, "category": "Instruction not followed"}]}]}
    sid = client.post("/suites/import", headers=auth, json={"format": "json", "content": json.dumps(suite)}).json()["id"]
    got = prompt("  suggest a HORROR story   (genre: comedy)")  # capitals and spaces don't matter
    assert (got["verdict"], got["category"]) == ("Fail", "Instruction not followed")
    assert got["expected"] == "Points out the conflict and asks which the person wants."
    assert [c.get("fromCase") for c in got["checks"]] == [None, f"{sid}/SG-001"]

    # A different prompt isn't affected.
    assert prompt("A dragon who is afraid of fire (genre: fantasy)")["verdict"] == "Pass"

    # Change the suite (here: loosen the check) and the next identical prompt follows the change.
    client.patch(f"/suites/{sid}/cases/SG-001", headers=auth, json={"checks": [{"type": "max_length", "max": 2000}]})
    assert prompt("Suggest a horror story (genre: comedy)")["verdict"] == "Pass"
