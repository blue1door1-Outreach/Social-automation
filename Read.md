# **Khujе Nao — complete automation plan**

Before changing or running the code, we should treat this as a small production system, not just a script that posts every morning. The goal is **reliable, reviewable daily content for Facebook and Instagram, with no accidental duplicate posts, no surprise charges, and a safe way to recover when something fails.**

One important distinction: “zero-cost” can be the target, but it cannot be guaranteed forever. Free-tier limits, API access, platform rules, and account eligibility can change. We’ll design the system so it stops safely rather than silently creating costs or publishing questionable content.

## **1. What the finished system will do**

Daily workflow

**Before the scheduled publishing window**

GitHub Actions starts the Python workflow.

**Research**

- Collect relevant trend and news signals.
- Filter out irrelevant, sensitive, stale, or unreliable topics.
- Choose a topic that fits Khujе Nao's actual products.

**Create**

- Generate an original caption and hashtags.
- Create a branded graphic with Pillow.
- Check image dimensions, text overflow, and required fields.

**Quality and safety checks**

- Validate the caption and image.
- Check for duplicates.
- Confirm the target accounts and image URL.
- Stop if any critical check fails.

**Preview and approval**

- Save the post preview as an artifact.
- Start with automatic publishing disabled.
- Review the first posts before enabling queueing.

**Publish through Buffer**

- Queue separately for Facebook and Instagram.
- Record the result for each platform.
- Report failures without blindly retrying.

## **2. Edge cases we need to handle**

These are the main failure scenarios and the protections I recommend.

| Area               | Possible problem                                                | Protection                                                                 |
| ------------------ | --------------------------------------------------------------- | -------------------------------------------------------------------------- |
| Trend research     | RSS feed is unavailable or empty                                | Use a fallback source; if all sources fail, skip the post                  |
| Trend relevance    | A popular topic has nothing to do with the shop                 | Require a relevance check against the shop's real products                 |
| News quality       | A headline is misleading or outdated                            | Use trends as inspiration, not as verified facts                           |
| AI generation      | AI invents prices, discounts, product features, or stock        | Only use product facts supplied in approved shop configuration             |
| AI service         | Gemini quota is exhausted or API is unavailable                 | Retry briefly, then save an error report and stop                          |
| Generated text     | Caption is too long, repetitive, or contains unsupported claims | Validate length, content, and required fields                              |
| Image creation     | Text gets cut off or image file is corrupt                      | Check dimensions, file type, readability, and successful image decoding    |
| Image URL          | GitHub Pages has not deployed the image yet                     | Verify the public image URL before sending it to Buffer                    |
| Instagram          | Image format or account connection is unsupported               | Validate image format and test the connected Instagram account             |
| Facebook           | Page connection or permissions expire                           | Detect authorization errors and stop publishing                            |
| Buffer API         | API changes or a request fails                                  | Log the response; don't assume a request succeeded                         |
| Duplicate posting  | A workflow runs twice or gets manually restarted                | Use a daily unique post ID and check publishing history                    |
| Partial publishing | Facebook succeeds but Instagram fails                           | Track each platform separately; retry only the failed destination          |
| GitHub Actions     | Scheduled run is delayed or skipped                             | Monitor the last successful run; don't assume cron runs at an exact minute |
| Time zones         | Daylight saving time changes the local publishing time          | Make the timezone explicit and test the schedule                           |
| GitHub storage     | State file cannot be updated                                    | Fail safely and alert rather than assuming the post was recorded           |
| Costs              | A free quota runs out or a service changes its plan             | Set usage limits where possible; stop rather than switch to a paid service |
| Security           | API keys appear in logs or source code                          | Store secrets in GitHub Secrets; never print their values                  |
| Account access     | An account requires adult ownership or authorization            | Have a parent or guardian handle any account setup that requires an adult  |

## **3. The safeguards I would add before launch**

The existing ZIP is a useful starting point, but I would harden it before turning on automatic queueing.

**A. A strict publishing gate**

The system should only queue a post when all of these are true:

- Research completed or an approved fallback topic was selected.
- The generated caption passed validation.
- The image was created and passed image checks.
- The image is publicly accessible.
- The target Buffer channels were found and verified.
- The post has not already been queued for that date.
- Automatic queueing is explicitly enabled.

If a critical check fails, it should skip that day's post. Missing a post is better than publishing a broken or misleading one.

**B. Duplicate prevention**

Each daily post should have a unique identifier based on its date, topic, and content. The system should record Facebook and Instagram outcomes independently.

This matters because a network timeout does not necessarily mean Buffer rejected a request. Retrying blindly could create duplicates.

**C. Review mode**

For the first stage:

- Generate the post.
- Save the image and caption.
- Review them manually.
- Do not publish automatically.

Only after successful tests should we enable automatic Buffer queueing. I recommend keeping manual approval available even after launch.

**D. Recovery and monitoring**

The workflow should produce a readable report containing:

- Run date and time.
- Selected topic.
- Caption-generation status.
- Image-generation status.
- Facebook queue status.
- Instagram queue status.
- Any error messages, with secrets removed.

If a run fails, it should be possible to rerun it without duplicating posts that already succeeded.

## **4. Recommended project structure**

I would organize the final implementation like this:

```
khuje-nao-automation/
│
├── .github/
│   └── workflows/
│       └── daily-post.yml
│
├── config/
│   ├── brand.json
│   └── products.json
│
├── src/
│   ├── research.py
│   ├── topic_filter.py
│   ├── writer.py
│   ├── graphics.py
│   ├── validator.py
│   ├── buffer_client.py
│   ├── duplicate_guard.py
│   ├── state.py
│   └── main.py
│
├── tests/
│   ├── test_writer.py
│   ├── test_graphics.py
│   ├── test_validator.py
│   └── test_duplicates.py
│
├── requirements.txt
└── README.md
```

This separates research, writing, design, validation, publishing, and testing. It will make errors easier to find and fix.

## **5. Implementation phases**

1. **Phase 1 — Brand configuration**

   Define the shop description, real products, target audience, location, language, brand colors, tone, and approved claims.
2. **Phase 2 — Research engine**

   Collect trend signals, filter irrelevant topics, and handle unavailable sources.
3. **Phase 3 — Content generation**

   Generate original captions and create branded graphics with Pillow.
4. **Phase 4 — Validation and testing**

   Test invalid captions, missing images, repeated topics, unavailable APIs, and partial failures.
5. **Phase 5 — Buffer integration**

   Verify channel IDs, image accessibility, API responses, and separate platform results.
6. **Phase 6 — GitHub Actions scheduling**

   Configure the daily schedule and confirm the timezone.
7. **Phase 7 — Supervised launch**

   Run in preview mode, inspect several posts, then enable queueing only after successful tests.

## **6. What I will not assume**

- That Khujе Nao sells any particular product until you confirm it.
- That every trend is appropriate for a shop post.
- That AI-generated product images accurately represent real stock.
- That Facebook and Instagram will always accept identical content.
- That free API access or free hosting will remain unlimited.
- That a scheduled GitHub Action will always start at the exact minute.
- That Buffer queueing means a post has successfully appeared on both platforms.

## **7. Two decisions before implementation**

The most important missing detail is the publishing timezone. GitHub Actions cron uses UTC, so we need to convert your local 10 AM target correctly.

**Which timezone should the daily schedule use?** For example, `America/New_York` or `Asia/Dhaka`.

Once that's settled, the next step is to configure the brand and product information, then build and test the hardened version before enabling publishing.