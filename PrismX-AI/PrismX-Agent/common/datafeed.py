import os, csv, io, gspread
from google.oauth2.service_account import Credentials

SHEET_ID = "1xuBznN7IRgsMkmGRT4lTFf2yry4caqgITdvzZfFXIJM"
KEY_PATH = "/home/student_02_8a37cde7a746/adk_mcp_tools/google_maps_mcp_agent/common/mcp/service_account.json"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

DATA = {
    "employees": """worker_id,worker_type,name,role,team,manager_role,location,country,employment_status,start_date
AE-1001,Employee,Alex Carter,Software Engineer,Platform Eng,Associate Director,Louisville,KY,Active,2023-01-09
AE-1002,Employee,Jordan Singh,Data Engineer,Data Platforms,Associate Director,Louisville,KY,Active,2022-10-17
AE-1003,Employee,Samira Patel,QA Analyst,Quality Eng,Associate Director,Louisville,KY,Active,2021-08-02
AE-1004,Employee,Chris Nguyen,Site Reliability Engineer,Infra & SRE,Associate Director,Louisville,KY,Active,2022-02-14
AE-1005,Employee,Elena Rossi,Business Analyst,Corporate Services IT,Associate Director,Louisville,KY,Active,2020-06-15
AE-1006,Employee,Marcus Lee,Solutions Architect,Architecture,Associate Director,Louisville,KY,Active,2019-09-09
AE-1007,Employee,Grace Kim,Product Owner,Corporate Services IT,Associate Director,Louisville,KY,Active,2021-03-22
AE-1008,Employee,Diego Alvarez,Data Analyst,Analytics,Associate Director,Louisville,KY,Active,2023-04-03
AC-2001,Contractor,Riya Mehta,Software Engineer,Platform Eng,Associate Director,Remote,US,Active,2024-01-08
AC-2002,Contractor,Tom Becker,QA Analyst,Quality Eng,Associate Director,Remote,US,Active,2023-11-06
AC-2003,Contractor,Liam O'Brien,Data Engineer,Data Platforms,Associate Director,Remote,US,Active,2023-09-11
AC-2004,Contractor,Chen Wei,Integration Engineer,Integration,Associate Director,Remote,US,Active,2023-07-17
AC-2005,Contractor,Amira Hassan,Reporting Analyst,Analytics,Associate Director,Remote,US,Active,2023-12-04
AC-2006,Contractor,Noah Johnson,Support Engineer,Service Ops,Associate Director,Remote,US,Active,2024-02-12
AC-2007,Contractor,Sofia Garcia,Data Analyst,Analytics,Associate Director,Remote,US,Active,2024-03-11
AC-2008,Contractor,Pedro Silva,DevOps Engineer,Infra & SRE,Associate Director,Remote,US,Active,2023-08-14
AC-2009,Contractor,Hannah Lee,Technical Writer,Corporate Services IT,Associate Director,Remote,US,Active,2023-10-02
AC-2010,Contractor,Ethan Brown,Service Desk Analyst,Service Ops,Associate Director,Remote,US,Active,2023-05-22
AC-2011,Contractor,Mina Park,Automation Engineer,Platform Eng,Associate Director,Remote,US,Active,2024-04-01
AC-2012,Contractor,Arjun Rao,Database Engineer,Data Platforms,Associate Director,Remote,US,Active,2023-06-19
AC-2013,Contractor,Valentina Cruz,UX Researcher,Corporate Services IT,Associate Director,Remote,US,Active,2023-09-25
AC-2014,Contractor,Oliver Smith,Monitoring Specialist,Infra & SRE,Associate Director,Remote,US,Active,2023-12-11
AC-2015,Contractor,Keiko Tanaka,Build Engineer,Platform Eng,Associate Director,Remote,US,Active,2023-11-20
AC-2016,Contractor,Jason Clark,Integration Engineer,Integration,Associate Director,Remote,US,Active,2024-01-29
""",
    "cmdb": """app_id,app_name,app_category,owner_team,technology_family
APP-001,VSCode,IDE,Platform Eng,Development
APP-002,GitHub,Source Control,Platform Eng,SCM
APP-003,Jira,Ticketing,Service Ops,Ticketing
APP-004,ServiceNow,Ticketing,Service Ops,Ticketing
APP-005,Confluence,Documentation,Corporate Services IT,Knowledge
APP-006,Outlook,Email,Corporate Services IT,Communication
APP-007,Teams,Collaboration,Corporate Services IT,Communication
APP-008,Zoom,Collaboration,Corporate Services IT,Communication
APP-009,Splunk,Monitoring,Infra & SRE,Monitoring
APP-010,Azure Portal,Cloud Platform,Infra & SRE,Cloud
APP-011,Power BI,Analytics/BI,Analytics,BI
APP-012,Databricks,Data Platform,Data Platforms,Data
APP-013,SSMS,Database,Data Platforms,Database
""",
    "activity_logs": """date,worker_id,app_name,app_category,activity_observed,duration_seconds,signal_confidence
2025-10-26,AE-1001,VSCode,IDE,Development,5400,0.92
2025-10-26,AE-1001,GitHub,Source Control,Integration,1800,0.88
2025-10-26,AE-1001,Teams,Collaboration,Meeting,3600,0.85
2025-10-26,AC-2003,Databricks,Data Platform,Data Engineering,7200,0.91
2025-10-26,AC-2003,Power BI,Analytics/BI,Reporting,2400,0.86
2025-10-26,AE-1004,Splunk,Monitoring,Monitoring,5400,0.82
2025-10-26,AE-1004,Azure Portal,Cloud Platform,Operations,3600,0.84
2025-10-27,AE-1002,Databricks,Data Platform,Data Engineering,7200,0.93
2025-10-27,AE-1002,SSMS,Database,Analysis,3600,0.89
2025-10-27,AC-2004,Jira,Ticketing,Ticket Handling,2700,0.87
2025-10-27,AC-2004,ServiceNow,Ticketing,Ticket Handling,2400,0.86
2025-10-27,AE-1006,Confluence,Documentation,Documentation,1800,0.9
2025-10-27,AE-1006,Teams,Collaboration,Meeting,3600,0.83
2025-10-28,AC-2008,Azure Portal,Cloud Platform,Operations,5400,0.88
2025-10-28,AC-2008,Splunk,Monitoring,Monitoring,3600,0.82
2025-10-28,AC-2011,GitHub,Source Control,Integration,2400,0.87
2025-10-28,AC-2011,VSCode,IDE,Development,4800,0.9
2025-10-28,AE-1003,Teams,Collaboration,Meeting,3600,0.8
2025-10-29,AE-1005,Power BI,Analytics/BI,Reporting,5400,0.91
2025-10-29,AE-1005,Confluence,Documentation,Documentation,1800,0.9
2025-10-29,AC-2012,SSMS,Database,Analysis,3600,0.85
2025-10-29,AC-2012,Databricks,Data Platform,Data Engineering,5400,0.9
2025-10-29,AE-1007,Outlook,Email,Communication,2400,0.86
2025-10-29,AE-1007,Jira,Ticketing,Ticket Handling,1800,0.84
2025-10-30,AC-2006,ServiceNow,Ticketing,Ticket Handling,3600,0.86
2025-10-30,AC-2006,Teams,Collaboration,Meeting,2700,0.81
2025-10-30,AE-1008,Power BI,Analytics/BI,Analysis,5400,0.9
2025-10-30,AE-1008,Confluence,Documentation,Documentation,1800,0.88
2025-10-30,AC-2010,Teams,Collaboration,Meeting,3600,0.82
2025-10-31,AE-1001,VSCode,IDE,Development,7200,0.93
2025-10-31,AE-1001,GitHub,Source Control,Integration,2700,0.9
2025-10-31,AE-1004,Splunk,Monitoring,Monitoring,5400,0.83
2025-10-31,AC-2009,Confluence,Documentation,Documentation,2400,0.88
2025-10-31,AC-2009,Outlook,Email,Communication,1800,0.86
2025-11-01,AE-1002,Databricks,Data Platform,Data Engineering,7200,0.92
2025-11-01,AE-1002,SSMS,Database,Analysis,3600,0.9
2025-11-01,AE-1006,Teams,Collaboration,Meeting,3600,0.83
2025-11-01,AC-2011,VSCode,IDE,Development,5400,0.91
2025-11-01,AC-2011,GitHub,Source Control,Integration,2400,0.88
2025-11-01,AC-2004,Jira,Ticketing,Ticket Handling,3600,0.87
""",
    "taxonomy_weights": """category,label,weight
IDE,Development,0.85
Source Control,Integration,0.82
Ticketing,Ticket Handling,0.8
Collaboration,Meeting,0.78
Monitoring,Oncall/Monitoring,0.76
Email,Communication,0.7
Documentation,Documentation,0.74
Cloud Platform,Operations,0.79
Analytics/BI,Reporting,0.81
Database,Analysis,0.8
Data Platform,Data Engineering,0.83
"""
}

def csv_to_matrix(csv_text: str):
    rdr = csv.reader(io.StringIO(csv_text.strip()))
    return [row for row in rdr]

def upsert_tab(sh, tab_name: str, values: list[list[str]]):
    try:
        ws = sh.worksheet(tab_name)
        ws.clear()
    except Exception:
        ws = sh.add_worksheet(title=tab_name, rows=len(values)+10, cols=len(values[0])+10)
    ws.update('A1', values, value_input_option='RAW')

def main():
    creds = Credentials.from_service_account_file(KEY_PATH, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SHEET_ID)
    for tab, csv_text in DATA.items():
        values = csv_to_matrix(csv_text)
        upsert_tab(sh, tab, values)

if __name__ == "__main__":
    main()
