from database import (
    count_study_modules,
    get_actual_usage,
    get_audit_logs,
    initialize_database,
    load_users,
)


def main() -> None:
    initialize_database()
    print("CogniStudi MySQL database is ready.")
    print(f"Users: {len(load_users())}")
    print(f"Study modules: {count_study_modules()}")
    print(f"Usage rows this week: {int(get_actual_usage()['Tokens'].sum())}")
    print(f"Audit log entries: {len(get_audit_logs())}")


if __name__ == "__main__":
    main()
