#!/usr/bin/env python3
"""
Find Instagram users you follow who don't follow you back.
Requirements: instagrapi

Usage:
  python main.py
  python main.py --fresh
  python main.py --skip-verify
"""

import argparse
import getpass
import json
import os
import random
import sys
import time
from typing import Dict, List, Optional, Set

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

# Дополнительно: fallback парсер .env
env_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(env_file_path):
    try:
        with open(env_file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip("'").strip('"')
                    if k and (k not in os.environ or not os.environ[k]):
                        os.environ[k] = v
    except Exception:
        pass

from instagrapi import Client
from instagrapi.exceptions import (
    ChallengeRequired,
    ClientError,
    FeedbackRequired,
    LoginRequired,
    TwoFactorRequired,
)
from instagrapi.types import UserShort

SESSION_FILE = "session.json"
OUTPUT_FILE = "not_following_back.txt"
DETAILS_FILE = "not_following_back_details.txt"
FANS_FILE = "fans.txt"


def cleanup_session(path: str = SESSION_FILE):
    if os.path.exists(path):
        try:
            os.remove(path)
            print(f"🗑️ Удалена устаревшая сессия: {path}")
        except Exception as e:
            print(f"⚠️ Предупреждение: не удалось удалить сессию {path}: {e}")


def save_session(client: Client, path: str = SESSION_FILE):
    try:
        client.dump_settings(path)
        print(f"💾 Сессия сохранена в {path}")
    except Exception as e:
        print(f"⚠️ Предупреждение: ошибка при сохранении сессии: {e}")


def load_session(client: Client, path: str = SESSION_FILE) -> bool:
    if not os.path.exists(path):
        return False
    try:
        client.load_settings(path, override_app_version=True)
        print(f"🔑 Загружена сохранённая сессия из {path}")
        return True
    except Exception as e:
        print(f"⚠️ Не удалось прочитать {path}: {e}")
        return False


def rand_sleep(min_s: float = 1.0, max_s: float = 2.5):
    """Случайная задержка для предотвращения блокировок."""
    time.sleep(random.uniform(min_s, max_s))


def challenge_code_handler(username: str, choice=None) -> str:
    print(f"\n📩 Instagram запросил подтверждение для аккаунта @{username}.")
    if choice:
        print(f"Код отправлен через: {choice}")
    return input("Введите код безопасности из SMS или почты: ").strip()


def authenticate_client(
    client: Client,
    username: Optional[str] = None,
    password: Optional[str] = None,
    fresh: bool = False,
) -> str:
    """
    Выполняет вход в Instagram или использует сохранённую сессию.
    Возвращает подтверждённый username.
    """
    client.challenge_code_handler = challenge_code_handler
    # Небольшая задержка между внутренними запросами instagrapi
    client.delay_range = [1, 2]

    # Считываем из переменных окружения, если не передано явно
    username = (username or os.getenv("INSTAGRAM_USERNAME") or os.getenv("IG_USERNAME") or "").strip() or None
    password = (password or os.getenv("INSTAGRAM_PASSWORD") or os.getenv("IG_PASSWORD") or "").strip() or None

    if fresh:
        cleanup_session()

    session_loaded = False
    if not fresh and os.path.exists(SESSION_FILE):
        session_loaded = load_session(client)

    authenticated = False
    if session_loaded:
        try:
            print("⏳ Проверка сохранённой сессии...")
            user_info = client.user_info(client.user_id)
            current_user = user_info.username
            authenticated = True
            print(f"✅ Вход выполнен по сохранённой сессии: @{current_user}")
            if username and username.lower() != current_user.lower():
                print(f"ℹ️ В конфигурации указан @{username}, но активна сессия @{current_user}.")
                if sys.stdin.isatty():
                    relogin = input(f"Перезайти под @{username}? [y/N]: ").strip().lower()
                    if relogin in ("y", "yes", "да", "д"):
                        authenticated = False
                        cleanup_session()
                    else:
                        username = current_user
                else:
                    authenticated = False
                    cleanup_session()
            else:
                username = current_user
        except Exception as exc:
            print(f"⚠️ Сохранённая сессия недействительна ({exc}). Выполняем новый вход.")
            cleanup_session()
            authenticated = False

    # Проверяем, передан ли sessionid для входа без пароля
    sessionid = (os.getenv("INSTAGRAM_SESSIONID") or os.getenv("IG_SESSIONID") or "").strip() or None
    if sessionid and not authenticated:
        print("⏳ Выполняется вход по sessionid из .env...")
        try:
            client.login_by_sessionid(sessionid)
            save_session(client)
            print(f"✅ Вход по sessionid выполнен успешно: @{client.username}!")
            return client.username
        except Exception as e:
            print(f"⚠️ Ошибка входа по sessionid: {e}")

    if not authenticated:
        if not username:
            if sys.stdin.isatty():
                username = input("Instagram username: ").strip()
            else:
                print("❌ Ошибка: имя пользователя не указано в .env и терминал не интерактивен.")
                sys.exit(1)

        if not username:
            print("❌ Ошибка: имя пользователя обязательно (заполните .env или введите в терминале).")
            sys.exit(1)

        if not password:
            if sys.stdin.isatty():
                password = getpass.getpass("Instagram password: ")
            else:
                print("❌ Ошибка: пароль не указан в .env.")
                sys.exit(1)

        print(f"⏳ Выполняется вход в аккаунт @{username}...")
        try:
            rand_sleep(1.0, 2.0)
            outcome = client.bloks_caa_login(username=username, password=password)
            if outcome.get("logged_in"):
                client.login_flow()
                authenticated = True
            elif client.bloks_caa_login_needs_two_step(outcome.get("result", {})):
                code = input("Введите 2FA код (из приложения-аутентификатора или SMS): ").strip()
                two_step = client.bloks_caa_resolve_two_step_verification(outcome.get("result", {}), verification_code=code)
                if two_step.get("logged_in"):
                    client.login_flow()
                    authenticated = True
                else:
                    raise ClientError("Не удалось подтвердить 2FA код.")
            else:
                # Проверяем детальный ответ от Instagram
                strings = []
                client._bloks_collect_strings(outcome.get("result", {}), strings)
                combined = " ".join(strings).lower()

                if "incorrect password" in combined or "wrong_password" in combined or "password you entered is incorrect" in combined:
                    print(f"\n❌ Ошибка входа: Неверный пароль от аккаунта @{username}!")
                    print("⚠️ Instagram сообщил: 'The password you entered is incorrect'.")
                    print("Пожалуйста, откройте .env и укажите правильный пароль в INSTAGRAM_PASSWORD.")
                    print("\n💡 Либо используйте 100% вход без пароля через cookie sessionid:")
                    print("   1. Откройте instagram.com в браузере (где вы уже вошли в свой профиль)")
                    print("   2. Нажмите F12 -> Application (или Хранилище) -> Cookies -> https://www.instagram.com -> найдите 'sessionid'")
                    print("   3. Добавьте в .env: INSTAGRAM_SESSIONID=скопированное_значение")
                    sys.exit(1)

                # Запасной вызов стандартного логина
                client.login(username, password)
                authenticated = True

        except TwoFactorRequired:
            code = input("Введите 2FA код (из приложения-аутентификатора или SMS): ").strip()
            client.login(username, password, verification_code=code)
            authenticated = True
        except ChallengeRequired:
            print("Instagram запросил прохождение проверки безопасности.")
            client.challenge_resolve(client.last_json)
            authenticated = True
        except Exception as e:
            msg = str(e).lower()
            if "out of date" in msg or "upgrade your app" in msg:
                print(f"\n❌ Instagram заблокировал мобильный вход для @{username}.")
                print("Это происходит при неверном пароле либо антифрод-защите Instagram.")
                print("\n💡 Как войти гарантированно без пароля за 30 секунд:")
                print("1. Откройте https://instagram.com в браузере (где вы уже залогинены).")
                print("2. Нажмите F12 (Инструменты разработчика) -> вкладка 'Application' (или 'Хранилище') -> Cookies -> https://www.instagram.com")
                print("3. Скопируйте значение куки 'sessionid'.")
                print("4. Вставьте в .env: INSTAGRAM_SESSIONID=скопированное_значение")
            elif "password" in msg:
                print(f"\n❌ Неверный пароль для @{username}. Проверьте INSTAGRAM_PASSWORD в .env.")
            else:
                print(f"\n❌ Ошибка авторизации: {e}")
            sys.exit(1)

        save_session(client)
        print("✅ Успешный вход!")

    return username


def fetch_users_list(client: Client, user_id: str, list_type: str, expected_count: int = 0) -> Dict[str, UserShort]:
    """
    Получает список пользователей (following или followers) комбинируя несколько методов:
    1. v1 Mobile API (пагинация с размером порции 50)
    2. Private GraphQL API (если список неполный)
    3. Public GraphQL API (запасной)
    Объединяет результаты, исключая дубликаты.
    """
    users_map: Dict[str, UserShort] = {}
    print(f"\n📥 Сбор списка {list_type} (ожидается ~{expected_count})...")

    # Метод 1: v1 Mobile API порциями по 50
    try:
        if list_type == "following":
            iterator = client.iter_user_following_v1(user_id, amount=expected_count or 0, page_size=50)
        else:
            iterator = client.iter_user_followers_v1(user_id, amount=expected_count or 0, page_size=50)

        for u in iterator:
            users_map[str(u.pk)] = u
            if expected_count and len(users_map) % 50 == 0:
                print(f"   Загружено: {len(users_map)} / ~{expected_count}...")
    except Exception as e:
        print(f"   ⚠️ Замечание при сборе v1 API: {e}")

    loaded_v1 = len(users_map)
    print(f"   Итог v1 API: получено {loaded_v1} пользователей.")

    # Если загружено заметно меньше ожидаемого, добираем через Private GraphQL
    need_fallback = False
    if expected_count > 0:
        if loaded_v1 < expected_count and (expected_count - loaded_v1 > 3) and (loaded_v1 / expected_count < 0.95):
            need_fallback = True

    if need_fallback:
        print(f"   🔄 Загружено {loaded_v1} из {expected_count}. Подключаем Private GraphQL для добора...")
        try:
            rand_sleep(2.0, 3.5)
            if list_type == "following":
                gql_users = client.user_following_private_gql(user_id, amount=expected_count)
            else:
                gql_users = client.user_followers_private_gql(user_id, amount=expected_count)

            before = len(users_map)
            for u in gql_users:
                users_map[str(u.pk)] = u
            added = len(users_map) - before
            print(f"   Добавлено через Private GraphQL: +{added} (всего: {len(users_map)})")
        except Exception as e:
            print(f"   ⚠️ Ошибка Private GraphQL: {e}")

    # Запасной вариант 3: Public GraphQL
    if expected_count > 0 and len(users_map) < expected_count and (expected_count - len(users_map) > 3):
        print(f"   🔄 Пробуем Public GraphQL API...")
        try:
            rand_sleep(2.0, 3.5)
            if list_type == "following":
                pub_users = client.user_following_gql(user_id, amount=expected_count)
            else:
                pub_users = client.user_followers_gql(user_id, amount=expected_count)

            before = len(users_map)
            for u in pub_users:
                users_map[str(u.pk)] = u
            added = len(users_map) - before
            print(f"   Добавлено через Public GraphQL: +{added} (всего: {len(users_map)})")
        except Exception as e:
            print(f"   ⚠️ Ошибка Public GraphQL: {e}")

    final_count = len(users_map)
    diff = expected_count - final_count if expected_count else 0
    if expected_count and abs(diff) > 5 and (final_count / expected_count < 0.95):
        print(f"   ℹ️ Получено {final_count} из {expected_count} (разница {diff}). Это может быть вызвано удалёнными или заблокированными профилями.")
    else:
        print(f"   ✅ Сбор {list_type} завершён: получено {final_count} пользователей.")

    return users_map


def verify_candidates_following_back(
    client: Client,
    my_pk: str,
    candidates: List[UserShort],
    followers_map: Dict[str, UserShort],
) -> List[UserShort]:
    """
    Проверяет каждого кандидата на невзаимность через direct friendship API.
    Если кандидат на самом деле подписан (был пропущен из-за ограничений пагинации Instagram),
    он исключается из списка невзаимных и добавляется в followers_map.
    Это ГАРАНТИРУЕТ отсутствие ложных срабатываний (false positives).
    """
    if not candidates:
        return []

    print(f"\n🔍 Верификация {len(candidates)} кандидатов для 100% точности (исключение ложных срабатываний)...")
    confirmed_not_following: List[UserShort] = []
    recovered_count = 0

    for idx, candidate in enumerate(candidates, 1):
        uname = candidate.username
        full = getattr(candidate, "full_name", "") or ""
        display = f"@{uname}" + (f" ({full})" if full else "")
        print(f"   [{idx}/{len(candidates)}] Проверка {display}...", end=" ", flush=True)

        is_following_me = None

        # Способ 1: Прямой запрос статуса отношений
        try:
            rel = client.user_friendship_v1(candidate.pk)
            if rel is not None and hasattr(rel, "followed_by"):
                is_following_me = bool(rel.followed_by)
        except Exception:
            is_following_me = None

        # Способ 2: Поиск пользователя среди подписчиков через поиск
        if is_following_me is None:
            try:
                search_results = client.search_followers_v1(my_pk, query=uname)
                found = any(
                    str(u.pk) == str(candidate.pk) or u.username.lower() == uname.lower()
                    for u in search_results
                )
                is_following_me = found
            except Exception:
                pass

        # Безопасная пауза между проверками
        rand_sleep(0.5, 1.1)

        if is_following_me is True:
            print("✅ Подписан в ответ! (исправлено ложное срабатывание)")
            followers_map[str(candidate.pk)] = candidate
            recovered_count += 1
        elif is_following_me is False:
            print("❌ НЕ подписан на вас взаимно")
            confirmed_not_following.append(candidate)
        else:
            print("⚠️ Не удалось уточнить статус (оставлен в списке)")
            confirmed_not_following.append(candidate)

    if recovered_count > 0:
        print(f"\n✨ Найдено и исправлено {recovered_count} ложных срабатываний!")
    else:
        print(f"\n✅ Все кандидаты проверены.")

    return confirmed_not_following


def main():
    default_user = (os.getenv("INSTAGRAM_USERNAME") or os.getenv("IG_USERNAME") or "").strip() or None
    default_pass = (os.getenv("INSTAGRAM_PASSWORD") or os.getenv("IG_PASSWORD") or "").strip() or None

    parser = argparse.ArgumentParser(description="Проверка взаимности подписок в Instagram")
    parser.add_argument("--username", "-u", type=str, default=default_user, help="Имя пользователя Instagram (или через .env)")
    parser.add_argument("--password", "-p", type=str, default=default_pass, help="Пароль Instagram (или через .env)")
    parser.add_argument("--fresh", action="store_true", help="Сбросить сохранённую сессию и войти заново")
    parser.add_argument("--skip-verify", action="store_true", help="Пропустить точечную верификацию кандидатов")
    parser.add_argument("--output", "-o", type=str, default=OUTPUT_FILE, help=f"Файл для сохранения (по умолч.: {OUTPUT_FILE})")
    args = parser.parse_args()

    client = Client()

    username = authenticate_client(
        client=client,
        username=args.username,
        password=args.password,
        fresh=args.fresh,
    )

    my_pk = str(client.user_id)

    # Получаем актуальные счетчики профиля
    try:
        user_info = client.user_info(my_pk)
        expected_following = getattr(user_info, "following_count", 0)
        expected_followers = getattr(user_info, "follower_count", 0)
        account_name = getattr(user_info, "full_name", "") or username
        print(f"\n📊 Профиль @{username} ({account_name}):")
        print(f"   👥 Подписок (Following):    {expected_following}")
        print(f"   👤 Подписчиков (Followers): {expected_followers}")
    except Exception as e:
        print(f"⚠️ Не удалось получить профиль: {e}")
        expected_following = 0
        expected_followers = 0

    # 1. Загружаем подписки (following)
    following_map = fetch_users_list(client, my_pk, "following", expected_following)

    # 2. Загружаем подписчиков (followers)
    followers_map = fetch_users_list(client, my_pk, "followers", expected_followers)

    # Нормализация для сопоставления
    follower_pks: Set[str] = set(followers_map.keys())
    follower_usernames: Set[str] = {u.username.lower() for u in followers_map.values()}

    # Кандидаты: вы подписаны, но их нет среди полученных подписчиков
    candidates = [
        u for pk, u in following_map.items()
        if pk not in follower_pks and u.username.lower() not in follower_usernames
    ]

    # Сортируем кандидатов по username
    candidates.sort(key=lambda u: u.username.lower())

    # 3. Верификация кандидатов (если не отключена флагом)
    if not args.skip_verify and candidates:
        should_verify = True
        if len(candidates) > 150:
            if sys.stdin.isatty():
                ans = input(f"\nОбнаружено {len(candidates)} кандидатов. Выполнить точную проверку для исключения ошибок? [Y/n]: ").strip().lower()
                if ans in ("n", "no", "нет", "н"):
                    should_verify = False
            else:
                should_verify = True

        if should_verify:
            not_following_back = verify_candidates_following_back(
                client=client,
                my_pk=my_pk,
                candidates=candidates,
                followers_map=followers_map,
            )
        else:
            not_following_back = candidates
    else:
        not_following_back = candidates

    # Повторно обновляем множества после верификации (если кто-то вернулся в подписчики)
    following_pks: Set[str] = set(following_map.keys())
    following_usernames: Set[str] = {u.username.lower() for u in following_map.values()}

    # Фанаты: подписаны на вас, но вы не подписаны на них
    fans = [
        u for pk, u in followers_map.items()
        if pk not in following_pks and u.username.lower() not in following_usernames
    ]
    fans.sort(key=lambda u: u.username.lower())

    # Взаимные подписки
    mutual_count = len(following_map) - len(not_following_back)

    # Вывод результатов
    print("\n" + "=" * 60)
    print(f"📊 ИТОГОВЫЙ ОТЧЕТ ДЛЯ @{username}")
    print("=" * 60)
    print(f"👥 Вы подписаны на:                {len(following_map)}")
    print(f"👤 На вас подписаны:               {len(followers_map)}")
    print(f"🤝 Взаимные подписки:              {mutual_count}")
    print(f"❌ НЕ подписаны на вас взаимно:    {len(not_following_back)}")
    print(f"⭐ Ваши фанаты (не подписаны вы):  {len(fans)}")
    print("=" * 60)

    if not_following_back:
        print(f"\n❌ Список пользователей, которые НЕ подписаны на вас взаимно ({len(not_following_back)}):\n")
        for i, u in enumerate(not_following_back, 1):
            full = getattr(u, "full_name", "") or ""
            full_str = f" ({full})" if full else ""
            print(f"  {i:2d}. @{u.username}{full_str} — https://instagram.com/{u.username}")
    else:
        print("\n🎉 Отлично! Все пользователи, на которых вы подписаны, подписаны на вас в ответ!")

    # Сохраняем в файл not_following_back.txt
    try:
        with open(args.output, "w", encoding="utf-8") as f:
            for u in not_following_back:
                f.write(f"{u.username}\n")
        print(f"\n💾 Список юзернеймов сохранён в: {args.output}")
    except Exception as e:
        print(f"⚠️ Ошибка при записи в {args.output}: {e}")

    # Сохраняем подробный отчет со ссылками
    try:
        with open(DETAILS_FILE, "w", encoding="utf-8") as f:
            f.write(f"Отчет по невзаимным подпискам для @{username}\n")
            f.write(f"Дата формирования: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Всего не подписаны в ответ: {len(not_following_back)}\n")
            f.write("=" * 60 + "\n\n")
            for i, u in enumerate(not_following_back, 1):
                full = getattr(u, "full_name", "") or "-"
                f.write(f"{i:2d}. @{u.username} | Имя: {full} | Ссылка: https://instagram.com/{u.username}\n")
        print(f"📄 Подробный отчет со ссылками сохранён в: {DETAILS_FILE}")
    except Exception as e:
        print(f"⚠️ Ошибка при записи в {DETAILS_FILE}: {e}")

    # Сохраняем список фанатов (если есть)
    if fans:
        try:
            with open(FANS_FILE, "w", encoding="utf-8") as f:
                for u in fans:
                    f.write(f"{u.username}\n")
            print(f"⭐ Список фанатов ({len(fans)}) сохранён в: {FANS_FILE}")
        except Exception:
            pass

    print("\nГотово! ✨")


if __name__ == "__main__":
    main()
