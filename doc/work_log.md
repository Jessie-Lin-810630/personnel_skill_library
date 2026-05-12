# 20260423 Work log
1. Initiated the project description in README.md, describing the goal of project and planned developmet items.
2. Initiated git branch feature/etl-pipeline
3. Initiated virtual environment by using pyenv + poetry. Used python 3.14.
4. Installed the python tools by
    ```bash
        poetry add pymongo python-frontmatter python-dotenv loguru

        # pymongo: for connection to MongoDB
        # python-frontmatter: for parsing the frontmatter in each .md file in vault.
        # logura: for saving/showing logs humanfriendly
    ```
5. Built the early folder structure and summarized it in [doc/project_structure_feature-etl-pipeline.md](project_structure_feature-etl-pipeline.md).

6. Create .env files. The contents in .env followed the requirements in the .env.example file.
7. Create four scripts that manages the ETL pipeline in task01-Obsidian.
8. Pre-run the pipeline and load the results to MongoDB on premises.
    ```bash
        poetry run python task01_obsidian_etl/main.py.
        # or:
        poetry run python -m task01_obsidian_etl.main
    ```
9. Establish the unit tests for task01.

# 20260428 Work log
1. Read the [official docs](https://docs.github.com/en/rest) about GitHub Rest API as references in task02.  
    In conclusion, there were three major documents guiding how to interact with endpoints of GitHun Rest API:
    - endpoint of listing repo: https://docs.github.com/en/rest/repos/repos?apiVersion=2026-03-10#list-repositories-for-the-authenticated-user
    - endpoint of listing commits:  https://docs.github.com/en/rest/commits/commits?apiVersion=2026-03-10#list-commits
    - endpoint of listing readme: https://docs.github.com/en/rest/repos/contents?apiVersion=2026-03-10#get-a-repository-readme
2. Create `Personal Access Token (classic)` and appended it to the .env file.
3. Created four scripts that manages the ETL pipeline in task02-github_restapi_etl.
4. Drafted the schema design of collections generated in this task in [doc/project_structure_feature-etl-pipeline.md](project_structure_feature-etl-pipeline.md). `This can be revised in the future if needed`.
5. Installed python module, `requests`, by executing :
    ```bash
        poetry add requests
    ```
6. Create four scripts to that manages the ETL pipeline in task02-github_restapi.
7. Pre-run the pipeline and load the results to MongoDB on premises.
    ```bash
        poetry run python task02_github_restapi_etl/main.py.
    ```

# 20260429 Work log
1. According to official documents(https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api?apiVersion=2026-03-10&versionId=free-pro-team%40latest&restPage=about-the-rest-api), added function _check_and_wait_rate_limit() for the prevention of exceeding rate-limit.
2. Consolidate the try-except in the [srcipt](../task02_github_restapi_etl/e_request_github_api.py) to make sure the 409, 429, 403 error can be captured and properly handled case by case.
3. Establish the unit tests for task02 and all the testing results are pass.

# 20260503 Work log
1. Searched available API endpoints from leetcode.com. The searching results showed that leetcode has been applying graphQL API to request documents and users' features for backend.
2. However, no official documents about querying practices for the graphQL API of leetcode were provided. Instead, used the [suggestions on Postman](https://documenter.getpostman.com/view/14486486/2s93sZ6tec#intro).
3. Through the pre-tests on Postman, concluded that two querying statements, `view solved problem for user` and `Question Number` were what we could used in this project. The particular techniques should be in attentions was two COOKIES, `LEECODE_SESSIOM` and `CRSF TOKEN` when HTTP request.
4. The execution results demonstrated that if the COOKIES were expired then HTTP request might failed (error 403). So, the [ETL task 03](../task03_leetcode_ccClub_etl/) requesting leetcode graphQL API needed manual log-in on browser beforehand in order to keep the COOKIES not expired. `The current ETL task03 was suitable for running on-premise. How to automatically refresh the COOKIES in period should be discussed when deployment.`
5. Append the environments variables required for calling `leetcode graphQL API` to the .env file.
6. Created four scripts performing ETL tasks for personal submission records on leetcode. The scripts were stored in [task03_leetcode_ccClub_etl](../task03_leetcode_ccClub_etl/).
7. Drafted the schema design of collections generated in this task in [doc/project_structure_feature-etl-pipeline.md](project_structure_feature-etl-pipeline.md). `This can be revised in the future if needed`.

# 20260505 Work log
1. Investigate if API endpoints available from ccClub judgement system that was another website for coding practices once registered. The investigating result showed that several endpoints featuring REST API was accessible.
2. The particular techniques should be in attentions was CRSF TOKEN in cookies when HTTP request. The token was given by server upon visit. To successfully extracting the personal coding practices records (like what users generally did on leetcode.com) in ETL pipeline, `CRSF TOKEN`, `username` and `password` were key points.
3. After pre-testing, already created four scripts performing ETL tasks for personal submission records on ccClub. The scripts were stored in [task03_leetcode_ccClub_etl](../task03_leetcode_ccClub_etl/).
4. Drafted the schema design of collections generated in this task in [doc/project_structure_feature-etl-pipeline.md](project_structure_feature-etl-pipeline.md). `This can be revised in the future if needed`.

# 20260508 Work log
1. Created a spreadsheet for scoring personal skills on the online google sheet.
2. Created a Service Account on GCP console, then generated and downloaded the JSON key of account.
3. Granted the Service Account "Editor" access to the google sheet.
4. Appended [doc/project_structure_feature-etl-pipeline.md](project_structure_feature-etl-pipeline.md), to addressed the schema design of collections generated by task05. `This can be revised in the future if needed`.
5. Inititated four scripts performing ETL tasks for personal skill scoring and statistical calculation. The scripts were stored in [task05_googlesheet_skill_etl](../task05_googlesheet_skill_etl/).
6. Appended the file path of JSON key to the .env file.
7. Polished the scripts at step 5 via Claude. After that, python-logger was added to improve readability. Also, dataframe.copy() method was implemented to a little lines to prevent from `SettingWithCopyWarning`.
8. Establish the unit tests for task05 and all the testing results are pass.

# 20260511 Work log
1. To branch `feature/etl-pipeline`, fixed the logistic transformation error about task02 that would repeatedly count the same commits in all branches so that the commit counts were overestimated.
2. To branch `feature/etl-pipeline`, fixed the design error on the upserting in the function `upsert_skill_scores` about task05.
3. To branch `feature/etl-pipeline`, correct the typo of label name on radar axis.