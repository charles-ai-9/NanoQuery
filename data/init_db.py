import sqlite3
import random
from datetime import datetime, timedelta


def init_db():
    conn = sqlite3.connect('mock_data.db')
    cursor = conn.cursor()

    # 1. 重建表结构：增加更多分析字段
    cursor.executescript("""
    DROP TABLE IF EXISTS users;
    DROP TABLE IF EXISTS credit_application;
    DROP TABLE IF EXISTS repayment_record;

    CREATE TABLE users (
        user_id INTEGER PRIMARY KEY,
        name TEXT,
        risk_level INTEGER,      -- 1:低, 2:中, 3:高
        region TEXT,             -- 地区，用于地理维度分析
        occupation TEXT          -- 职业，用于群体分析
    );

    CREATE TABLE credit_application (
        app_id INTEGER PRIMARY KEY,
        user_id INTEGER,
        apply_amount REAL,
        apply_time TEXT,
        status TEXT,             -- Approved, Rejected, Pending
        interest_rate REAL,
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    );

    CREATE TABLE repayment_record (
        id INTEGER PRIMARY KEY,
        app_id INTEGER,
        repayment_amount REAL,
        repayment_date TEXT,
        repayment_method TEXT,   -- Bank, Cash, ThirdParty
        status TEXT              -- Normal, Overdue, Partial
    );
    """)

    # 2. 造数据配置
    regions = ['北京', '上海', '广州', '深圳', '杭州', '成都']
    occupations = ['程序员', '教师', '医生', '个体户', '自由职业', '学生']

    # 3. 插入 50 个用户
    for i in range(1, 51):
        cursor.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?)",
                       (i, f"用户_{i}", random.choice([1, 1, 1, 2, 2, 3]),
                        random.choice(regions), random.choice(occupations)))

    # 4. 插入 150 条贷款申请
    start_date = datetime(2025, 1, 1)
    for i in range(1, 151):
        u_id = random.randint(1, 50)
        a_time = start_date + timedelta(days=random.randint(0, 120))
        cursor.execute("INSERT INTO credit_application VALUES (?, ?, ?, ?, ?, ?)",
                       (i, u_id, random.randint(5000, 100000),
                        a_time.strftime('%Y-%m-%d'),
                        random.choice(['Approved', 'Approved', 'Rejected']),
                        round(random.uniform(0.05, 0.15), 3)))

    # 5. 插入 200 条还款记录（埋入异常点）
    for i in range(1, 201):
        app_id = random.randint(1, 150)

        # 💡 埋雷点：4月12日 发生爆发式还款 (50笔)，模拟可疑资金流入
        if i <= 50:
            r_date = "2025-04-12"
            r_amount = random.randint(20000, 50000)  # 大额
        else:
            r_date = (start_date + timedelta(days=random.randint(0, 150))).strftime('%Y-%m-%d')
            r_amount = random.randint(1000, 10000)

        cursor.execute("INSERT INTO repayment_record VALUES (?, ?, ?, ?, ?, ?)",
                       (i, app_id, r_amount, r_date,
                        random.choice(['Bank', 'ThirdParty']),
                        random.choice(['Normal', 'Normal', 'Overdue'])))

    conn.commit()
    conn.close()
    print("✅ 数据库重构完成！共生成 50 名用户、150 条申请和 200 条还款记录（含 4.12 异常埋点）。")


if __name__ == "__main__":
    init_db()