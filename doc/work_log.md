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