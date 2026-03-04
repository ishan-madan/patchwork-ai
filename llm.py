"""
Duke Course Advisor
------------------------------------
Two-Stage LLM Filtering Architecture

Stage 1:
- LLM asks student up to 5 questions
- LLM selects most relevant subject code

Stage 2:
- Python filters courses by subject
- LLM selects best course from that subject

Requires:
- course_offerings.csv
- course_attributes.csv
- terms_offered.csv

Environment variable required:
export LITELLM_TOKEN="sk-xxxxxxxx"
"""

import os
import requests
import csv
import json


# --------------------------------------------------
# CONFIG
# --------------------------------------------------

DUKE_CHAT_URL = "https://litellm.oit.duke.edu/chat/completions"
DEFAULT_MODEL = "gpt-5-mini"
DEFAULT_TIMEOUT_SEC = 30
MAX_QUESTIONS = 5

COURSE_FILE = "data/course_offerings.csv"
ATTR_FILE = "data/course_attributes.csv"
TERM_FILE = "data/terms_offered.csv"


# --------------------------------------------------
# TOKEN + LLM CALL
# --------------------------------------------------

def get_token():
    token = os.getenv("LITELLM_TOKEN", "").strip()
    if token == "":
        raise RuntimeError("Missing LITELLM_TOKEN environment variable.")
    return token


def ask_llm(messages, model=DEFAULT_MODEL):
    token = get_token()

    headers = {
        "accept": "application/json",
        "Content-Type": "application/json",
        "x-litellm-api-key": token,
    }

    payload = {
        "model": model,
        "messages": messages,
    }

    resp = requests.post(
        DUKE_CHAT_URL,
        headers=headers,
        json=payload,
        timeout=DEFAULT_TIMEOUT_SEC,
    )

    if resp.status_code != 200:
        raise RuntimeError(resp.text)

    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


# --------------------------------------------------
# LOAD + MERGE COURSE DATA
# --------------------------------------------------

def load_courses():
    courses = {}

    # Load main course offerings
    with open(COURSE_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            crse_id = row["crse_id"]

            courses[crse_id] = {
                "crse_id": crse_id,
                "subject": row.get("subject", "").strip(),
                "catalog_nbr": row.get("catalog_nbr", "").strip(),
                "title": row.get("course_title_long", "").strip(),
                "description": row.get("descrlong", "")[:500],
                "units": row.get("units_minimum", "").strip(),
                "career": row.get("acad_career_lov_descr", "").strip(),
                "grading": row.get("grading_basis_lov_descr", "").strip(),
                "attributes": [],
                "terms_offered": []
            }

    # Load attributes
    with open(ATTR_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            crse_id = row["crse_id"]
            if crse_id in courses:
                attr_name = row.get("crse_attr_lov_descr", "")
                attr_value = row.get("crse_attr_value_lov_descr", "")
                combined = f"{attr_name} - {attr_value}".strip(" -")
                if combined:
                    courses[crse_id]["attributes"].append(combined)

    # Load terms offered
    with open(TERM_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            crse_id = row["crse_id"]
            if crse_id in courses:
                term = row.get("strm_lov_descr", "").strip()
                if term:
                    courses[crse_id]["terms_offered"].append(term)

    return list(courses.values())


def get_unique_subjects(courses):
    return sorted(set(c["subject"] for c in courses if c["subject"]))


def courses_to_string(courses):
    formatted = []

    for c in courses:
        formatted.append(f"""
Course ID: {c['crse_id']}
Code: {c['subject']} {c['catalog_nbr']}
Title: {c['title']}
Career: {c['career']}
Units: {c['units']}
Grading: {c['grading']}
Attributes: {", ".join(c['attributes'])}
Terms Offered: {", ".join(set(c['terms_offered']))}
Description: {c['description']}
""")

    return "\n".join(formatted)


# --------------------------------------------------
# PROMPTS
# --------------------------------------------------

def build_subject_prompt(subject_list):
    return f"""
You are a university academic advisor.

Your job:
- Ask the student about their academic interests, career goals,
  experience level, and preferences.
- Ask ONE question at a time.
- Ask NO MORE than 5 total questions.

After gathering enough information,
choose the MOST appropriate subject code from the list below.

Respond ONLY in JSON.

If you need more information:
{{
  "decision": "ask",
  "question": "<your question>"
}}

If ready to choose a subject:
{{
  "decision": "choose_subject",
  "subject": "<exact subject code from list>"
}}

Available subject codes:
{", ".join(subject_list)}
"""


def build_recommendation_prompt(course_text):
    return f"""
Based on the student's previous answers,
choose the BEST course from the list below.

Respond ONLY in JSON:

{{
  "decision": "recommend",
  "crse_id": "<crse_id>",
  "reason": "<clear explanation tied to the student's goals>"
}}

Courses:
{course_text}
"""


# --------------------------------------------------
# MAIN CONVERSATION
# --------------------------------------------------

def run_advisor():
    print("\n🎓 Duke AI Course Advisor\n")

    courses = load_courses()
    subjects = get_unique_subjects(courses)

    messages = [
        {"role": "system", "content": build_subject_prompt(subjects)}
    ]

    question_count = 0
    chosen_subject = None

    # -------- STAGE 1: SUBJECT SELECTION --------
    while question_count < MAX_QUESTIONS:

        response = ask_llm(messages)

        try:
            parsed = json.loads(response)
        except:
            print("Invalid JSON from LLM:")
            print(response)
            return

        if parsed["decision"] == "ask":
            print("\nAdvisor:", parsed["question"])
            user_input = input("You: ")

            messages.append({"role": "assistant", "content": response})
            messages.append({"role": "user", "content": user_input})

            question_count += 1

        elif parsed["decision"] == "choose_subject":
            chosen_subject = parsed["subject"]
            print(f"\n📚 Subject Selected: {chosen_subject}")
            break

    if not chosen_subject:
        print("Unable to determine subject.")
        return

    # -------- STAGE 2: COURSE RECOMMENDATION --------
    subject_courses = [
        c for c in courses if c["subject"] == chosen_subject
    ]

    if not subject_courses:
        print("No courses found for that subject.")
        return

    course_text = courses_to_string(subject_courses)

    messages.append({
        "role": "system",
        "content": build_recommendation_prompt(course_text)
    })

    final_response = ask_llm(messages)

    try:
        parsed = json.loads(final_response)
    except:
        print("Invalid JSON in recommendation stage:")
        print(final_response)
        return

    if parsed["decision"] == "recommend":
        crse_id = parsed["crse_id"]
        reason = parsed["reason"]

        match = next(
            (c for c in subject_courses if c["crse_id"] == crse_id),
            None
        )

        print("\n✅ Recommended Course\n")

        if match:
            print(f"{match['subject']} {match['catalog_nbr']} — {match['title']}")
            print(f"Units: {match['units']}")
            print(f"Career: {match['career']}")
            print("\nWhy this course?")
            print(reason)
        else:
            print("Course ID:", crse_id)
            print(reason)


# --------------------------------------------------
# ENTRY POINT
# --------------------------------------------------

if __name__ == "__main__":
    run_advisor()