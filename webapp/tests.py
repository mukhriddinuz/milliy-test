import json
import shutil
import tempfile
import time
from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from main.models import (
    BlockTest, BlockTestResult, BookTest, BookTestResult, Reklama, Subject, TelegramUser, Test, TestResult,
)
from main.telegram_auth import sign_init_data, validate_init_data

TOKEN = "123456:TEST-TOKEN"
TEST_MEDIA = tempfile.mkdtemp(prefix="milliy-test-media-")


def tearDownModule():
    shutil.rmtree(TEST_MEDIA, ignore_errors=True)


def init_data(user_id=111, **extra):
    fields = {"auth_date": int(time.time()), "user": {"id": user_id, "first_name": "Ali"}, **extra}
    return sign_init_data(fields, TOKEN)


@override_settings(TELEGRAM_BOT_TOKEN=TOKEN, WEBAPP_DEV_TELEGRAM_ID=None)
class InitDataTests(TestCase):
    def test_valid(self):
        data = validate_init_data(init_data(42))
        self.assertEqual(data["user"]["id"], 42)

    def test_tampered_user_id_rejected(self):
        raw = init_data(42).replace("%22id%22%3A42", "%22id%22%3A43")
        self.assertIsNone(validate_init_data(raw))

    def test_wrong_token_rejected(self):
        self.assertIsNone(validate_init_data(sign_init_data({"auth_date": int(time.time()), "user": {"id": 1}}, "1:OTHER")))

    def test_expired_rejected(self):
        old = sign_init_data({"auth_date": int(time.time()) - 3 * 86400, "user": {"id": 1}}, TOKEN)
        self.assertIsNone(validate_init_data(old))

    def test_garbage(self):
        for raw in ["", "abc", "hash=1", None]:
            self.assertIsNone(validate_init_data(raw))


@override_settings(TELEGRAM_BOT_TOKEN=TOKEN, WEBAPP_DEV_TELEGRAM_ID=None, MEDIA_ROOT=TEST_MEDIA)
@mock.patch("main.services.log_to_telegram")
@mock.patch("main.services.user_send_message")
@mock.patch("webapp.views.user_send_message")
class WebAppFlowTests(TestCase):
    def setUp(self):
        self.subject = Subject.objects.create(name="Matematika")

    def login(self, user_id=111, **extra):
        r = self.client.post(reverse("webapp:auth"), {"init_data": init_data(user_id, **extra), "next": "/"})
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def make_user(self, telegram_id=111):
        return TelegramUser.objects.create(
            telegram_id=telegram_id, name="Ali", surname="Valiyev", father_name="X",
            phone="+998901234567", region="Toshkent", district="Chinoz",
        )

    def make_test(self, creator, **kw):
        answers = {str(i): "A" for i in range(1, 33)}
        answers.update({"33": "E", "34": "F", "35": "A", "36": {"1": "OLMOQ"}, "37": {"1": "X", "2": "Y"}})
        return Test.objects.create(subject=self.subject, creator=creator, title="Matematika", answers=answers, **kw)

    # --- autentifikatsiya ---
    def test_unauthenticated_page_shows_auth_bootstrap(self, *_):
        r = self.client.get(reverse("webapp:home"))
        self.assertTemplateUsed(r, "webapp/auth.html")
        self.assertNotIn("X-Frame-Options", r.headers)
        self.assertIn("frame-ancestors", r.headers["Content-Security-Policy"])

    def test_auth_rejects_forged_data(self, *_):
        r = self.client.post(reverse("webapp:auth"), {"init_data": "user=%7B%22id%22%3A1%7D&auth_date=1&hash=abc"})
        self.assertEqual(r.status_code, 403)

    def test_auth_start_param_redirects_to_test(self, *_):
        data = self.login(start_param="test_15")
        self.assertEqual(data["next"], reverse("webapp:send_sheet", args=[15]))

    def test_auth_ignores_external_next(self, *_):
        r = self.client.post(reverse("webapp:auth"), {"init_data": init_data(), "next": "https://evil.example/"})
        self.assertEqual(r.json()["next"], reverse("webapp:home"))

    # --- ro'yxatdan o'tish ---
    def test_registration_uses_telegram_id_from_session(self, web_send, _, *__):
        self.login(777)
        r = self.client.get(reverse("webapp:create_option"))
        self.assertRedirects(r, reverse("webapp:register") + "?next=%2Fcreate_test%2F", fetch_redirect_response=False)
        r = self.client.post(reverse("webapp:register"), {
            "name": "Ali", "surname": "Valiyev", "father_name": "Karimovich", "phone": "+998901234567",
            "region": "Andijon", "district": "Asaka", "telegram_id": "1", "next": "/create_test/",
        })
        self.assertRedirects(r, "/create_test/", fetch_redirect_response=False)
        user = TelegramUser.objects.get()
        self.assertEqual(user.telegram_id, 777)
        web_send.assert_called_once()

    def test_registration_rejects_wrong_district(self, *_):
        self.login()
        r = self.client.post(reverse("webapp:register"), {
            "name": "A", "surname": "B", "father_name": "C", "phone": "+998901234567",
            "region": "Andijon", "district": "Chilonzor",
        })
        self.assertEqual(r.status_code, 200)
        self.assertFalse(TelegramUser.objects.exists())

    def test_banned_user_blocked(self, *_):
        user = self.make_user()
        user.is_banned = True
        user.save()
        self.login()
        self.assertEqual(self.client.get(reverse("webapp:home")).status_code, 403)

    # --- milliy sertifikat testi ---
    def test_create_national_test(self, _, service_send, *__):
        self.make_user()
        self.login()
        post = {f"q_{i}": "B" for i in range(1, 33)}
        post.update({"q_33": "E", "q_34": "F", "q_35": "C", "subject": self.subject.pk,
                     "written": json.dumps([["olmoq"], ["a", "b"]])})
        r = self.client.post(reverse("webapp:create_national"), post)
        test = Test.objects.get()
        self.assertRedirects(r, reverse("webapp:test_created", args=[test.pk]), fetch_redirect_response=False)
        self.assertEqual(test.questions_count, 37)
        self.assertEqual(test.answers["36"], {"1": "OLMOQ"})
        self.assertEqual(test.answers["37"], {"1": "A", "2": "B"})
        self.assertEqual(service_send.call_count, 2)

    def test_create_national_requires_all_answers_and_future_time(self, *_):
        self.make_user()
        self.login()
        post = {"subject": self.subject.pk, "q_1": "A", "is_public": "on", "channel_username": "@kanal",
                "start_time": (timezone.localtime() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")}
        r = self.client.post(reverse("webapp:create_national"), post)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Test.objects.exists())
        self.assertContains(r, "hozirgi vaqtdan keyin")

    def test_answer_sheet_does_not_leak_answers(self, *_):
        creator = self.make_user(1)
        self.make_user()
        test = self.make_test(creator)
        self.login()
        r = self.client.get(reverse("webapp:send_sheet", args=[test.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "OLMOQ")
        self.assertContains(r, 'name="w_37_2"')
        self.assertContains(r, 'name="q_35" value="F"')

    def test_submit_answers(self, _, service_send, *__):
        creator = self.make_user(1)
        user = self.make_user()
        test = self.make_test(creator)
        self.login()
        post = {f"q_{i}": "A" for i in range(1, 33)}
        post.update({"q_33": "E", "w_36_1": "olmoq", "w_37_1": "x", "w_37_2": "wrong"})
        r = self.client.post(reverse("webapp:send_sheet", args=[test.pk]), post)
        self.assertTemplateUsed(r, "webapp/submitted.html")
        result = TestResult.objects.get(user=user)
        self.assertEqual(result.correct_answers, 34)  # 32 + 33 + 36
        self.assertEqual(result.total_questions, 37)
        # natija o'quvchiga, "javob keldi" xabari muallifga ketadi
        recipients = [c.args[0] for c in service_send.call_args_list]
        self.assertEqual(recipients, [user.telegram_id, creator.telegram_id])

    def test_closed_or_future_test_rejected(self, *_):
        creator = self.make_user(1)
        self.make_user()
        closed = self.make_test(creator, is_active=False)
        future = self.make_test(creator, start_time=timezone.now() + timedelta(hours=2))
        self.login()
        for test in (closed, future):
            r = self.client.post(reverse("webapp:send_sheet", args=[test.pk]), {"q_1": "A"})
            self.assertTemplateUsed(r, "webapp/code_entry.html")
        self.assertFalse(TestResult.objects.exists())

    def test_code_entry_redirects(self, *_):
        creator = self.make_user()
        test = self.make_test(creator)
        self.login()
        r = self.client.get(reverse("webapp:send_test"), {"code": test.pk})
        self.assertRedirects(r, reverse("webapp:send_sheet", args=[test.pk]), fetch_redirect_response=False)
        r = self.client.get(reverse("webapp:send_test"), {"code": "999"})
        self.assertContains(r, "Test topilmadi")

    # --- DTM (blok) testlari ---
    def dtm_post(self, answer="A"):
        post = {"main_subject_1": "mathematics", "main_subject_2": "physics"}
        for key, n in [("main_1", 30), ("main_2", 30), ("ona_tili", 10), ("math_mandatory", 10), ("history", 10)]:
            post.update({f"{key}_{i}": answer for i in range(1, n + 1)})
        return post

    def test_create_dtm_builds_legacy_meta(self, *_):
        creator = self.make_user(1)
        self.login(1)
        r = self.client.post(reverse("webapp:create_dtm"), self.dtm_post("B"))
        test = BlockTest.objects.get()
        self.assertRedirects(r, reverse("webapp:dtm_created", args=[test.pk]), fetch_redirect_response=False)
        self.assertEqual(test.creator, creator)
        self.assertEqual(list(test.meta), ["ona_tili", "math_mandatory", "history", "mathematics", "physics"])
        self.assertEqual(test.meta["history"]["questions"]["21"], "B")
        self.assertEqual(test.meta["mathematics"]["point_per_question"], 3.1)
        self.assertEqual(sorted(test.meta["physics"]["questions"], key=int)[0], "61")
        self.assertEqual(test.max_score, 189.0)

    def test_dtm_same_subjects_rejected(self, *_):
        self.make_user()
        self.login()
        post = self.dtm_post()
        post["main_subject_2"] = "mathematics"
        r = self.client.post(reverse("webapp:create_dtm"), post)
        self.assertContains(r, "bir xil bo")
        self.assertFalse(BlockTest.objects.exists())

    def make_block_test(self, creator):
        from main.services import build_block_meta
        answers = {k: {str(i): "A" for i in range(1, n + 1)} for k, n in
                   [("main_1", 30), ("main_2", 30), ("ona_tili", 10), ("math_mandatory", 10), ("history", 10)]}
        return BlockTest.objects.create(creator=creator, meta=build_block_meta("mathematics", "physics", answers))

    def test_submit_dtm_all_correct(self, *_):
        test = self.make_block_test(self.make_user(1))
        user = self.make_user()
        self.login()
        r = self.client.get(reverse("webapp:dtm_sheet", args=[test.pk]))
        self.assertNotContains(r, '"questions"')  # test tuzilishi/javoblari sahifaga chiqmaydi
        post = {f"b{idx}_{i}": "A" for idx, n in enumerate([10, 10, 10, 30, 30]) for i in range(1, n + 1)}
        r = self.client.post(reverse("webapp:dtm_sheet", args=[test.pk]), post)
        self.assertTemplateUsed(r, "webapp/dtm_result.html")
        result = BlockTestResult.objects.get(user=user)
        self.assertEqual(result.total_score, 189.0)
        self.assertEqual(result.correct_answers, 90)
        # eski tizim formatida saqlanadi
        self.assertEqual(result.user_answers["mathematics"]["questions"]["31"], "A")

    def test_submit_dtm_with_certificates(self, *_):
        test = self.make_block_test(self.make_user(1))
        user = self.make_user()
        self.login()
        # 0-2: majburiy, 3: matematika (3.1), 4: fizika (2.1)
        r = self.client.post(reverse("webapp:dtm_sheet", args=[test.pk]),
                             {"cert_1": "on", "cert_3": "80", "b0_1": "A", "b4_1": "A"})
        self.assertTemplateUsed(r, "webapp/dtm_result.html")
        result = BlockTestResult.objects.get(user=user)
        d = result.detailed_results
        self.assertEqual(result.user_answers["math_mandatory"]["questions"], 11.0)
        self.assertEqual(d["math_mandatory"]["score"], 11.0)
        self.assertEqual(d["mathematics"]["score"], 80.0)
        self.assertEqual(d["ona_tili"]["score"], 1.1)
        self.assertEqual(d["physics"]["score"], 2.1)
        self.assertAlmostEqual(result.total_score, 94.2)

    def test_dtm_certificate_over_max_rejected(self, *_):
        test = self.make_block_test(self.make_user(1))
        self.make_user()
        self.login()
        r = self.client.post(reverse("webapp:dtm_sheet", args=[test.pk]), {"cert_4": "70"})
        self.assertContains(r, "oshmasligi kerak")
        self.assertFalse(BlockTestResult.objects.exists())

    # --- Kitob testlari ---
    def make_booktest(self, creator, **kw):
        answers = {str(i): "A" for i in range(1, 36)}
        answers["36"] = {"1": "X"}
        return BookTest.objects.create(subject=self.subject, creator=creator, title="Kitob 1",
                                       answers=answers, scores=[2] * 36, **kw)

    def test_booktest_slug_and_qr(self, *_):
        t1 = self.make_booktest(self.make_user(1))
        t2 = self.make_booktest(t1.creator)
        self.assertEqual((t1.slug, t2.slug), ("1", "2"))
        self.assertTrue(t1.qr_code.name.endswith("booktest_1.png"))
        self.assertIn("startapp=test_1", t1.qr_link())

    def test_start_param_prefers_booktest(self, *_):
        test = self.make_booktest(self.make_user(1))
        data = self.login(start_param=f"test_{test.slug}")
        self.assertEqual(data["next"], reverse("webapp:booktest_sheet", args=[test.slug]))
        data = self.login(start_param="test_999")
        self.assertEqual(data["next"], reverse("webapp:send_sheet", args=[999]))

    def test_submit_booktest_with_extra_ball(self, _, service_send, *__):
        test = self.make_booktest(self.make_user(1), extra_ball=True)
        user = self.make_user()
        self.login()
        r = self.client.get(reverse("webapp:booktest_sheet", args=[test.slug]))
        self.assertContains(r, 'name="extra_ball"')
        self.assertNotContains(r, ">X<")
        post = {f"q_{i}": "A" for i in range(1, 36)}
        post.update({"w_36_1": "x", "extra_ball": "30"})
        r = self.client.post(reverse("webapp:booktest_sheet", args=[test.slug]), post)
        self.assertTemplateUsed(r, "webapp/booktest_result.html")
        res = BookTestResult.objects.get(user=user)
        self.assertEqual(res.correct_answers, 36)
        self.assertEqual(res.score, (72 + 30) / 2)
        self.assertEqual(res.grade, "C+")
        # qayta topshirilsa statistika ikki marta sanalmaydi
        self.client.post(reverse("webapp:booktest_sheet", args=[test.slug]), post)
        test.refresh_from_db()
        self.assertEqual(test.correct_answers[0], 1)
        self.assertEqual(BookTestResult.objects.count(), 1)

    def test_booktest_open_for_users_create_admin_only(self, *_):
        test = self.make_booktest(self.make_user(1))
        self.make_user()
        self.login()
        # ishlash hammaga ochiq
        self.assertContains(self.client.get(reverse("webapp:send_test")), reverse("webapp:booktest"))
        self.assertEqual(self.client.get(reverse("webapp:booktest")).status_code, 200)
        self.assertEqual(self.client.get(reverse("webapp:booktest_sheet", args=[test.slug])).status_code, 200)
        # yaratish faqat adminlar uchun
        self.assertNotContains(self.client.get(reverse("webapp:create_option")), reverse("webapp:booktest_create"))
        self.assertEqual(self.client.get(reverse("webapp:booktest_create")).status_code, 403)

    def test_booktest_create_admin_only(self, *_):
        user = self.make_user()
        self.login()
        self.assertEqual(self.client.get(reverse("webapp:booktest_create")).status_code, 403)
        user.is_admin = True
        user.save()
        post = {f"q_{i}": "B" for i in range(1, 36)}
        post.update({"subject": self.subject.pk, "title": "Kitob A", "book_test": "on",
                     "written": json.dumps([["olma"]]), "scores": json.dumps([1.5] * 36)})
        with mock.patch("main.services.bot"):
            r = self.client.post(reverse("webapp:booktest_create"), post)
        test = BookTest.objects.get()
        self.assertRedirects(r, reverse("webapp:booktest_created", args=[test.slug]), fetch_redirect_response=False)
        self.assertEqual(test.questions_count, 36)
        self.assertEqual(test.answers["36"], {"1": "OLMA"})
        self.assertEqual(test.scores[0], 1.5)


class BlockScoringTests(TestCase):
    """Eski tizim (ser-bot) qoidalari: majburiy 1.1, asosiy fan point_per_question, sertifikat — son."""

    def setUp(self):
        self.test = BlockTest(meta={
            "ona_tili": {"type": "mandatory", "questions": {str(i): "A" for i in range(1, 11)}},
            "mathematics": {"type": "optional", "point_per_question": 3.1,
                            "questions": {str(i): "B" for i in range(31, 61)}},
        })

    def test_regular_answers(self):
        total, correct, d = self.test.calculate_score({
            "ona_tili": {"questions": {"1": "A", "2": "A", "3": "C"}},
            "mathematics": {"questions": {"31": "B"}},
        })
        self.assertEqual((total, correct), (5.3, 3))
        self.assertEqual(d["ona_tili"]["score"], 2.2)

    def test_certificate_number(self):
        total, correct, _ = self.test.calculate_score({"mathematics": {"questions": 93}, "ona_tili": {"questions": 11}})
        self.assertEqual((total, correct), (104.0, 40))

    def test_certificate_capped(self):
        total, _, _ = self.test.calculate_score({"mathematics": {"questions": 150}})
        self.assertEqual(total, 93.0)

    def test_legacy_local_numbering(self):
        # eski frontend asosiy fanni 1..30 bilan yuborgan
        total, correct, _ = self.test.calculate_score({"mathematics": {"questions": {"1": "B", "2": "B"}}})
        self.assertEqual((total, correct), (6.2, 2))


class ReklamaFlowTests(TestCase):
    def setUp(self):
        self.admin = TelegramUser.objects.create(telegram_id=10, name="A", surname="B", phone="+998901234567",
                                                 region="Toshkent", district="Chinoz", is_admin=True)
        for i in range(3):
            TelegramUser.objects.create(telegram_id=100 + i, name="U", surname=str(i), phone="+998901234567",
                                        region="Toshkent", district="Chinoz")

    def test_parse_buttons(self):
        r = Reklama.objects.create(admin_user_id=10, message_type="text",
                                   text="Salom [[sayt](https://a.uz)]\n[[Kanal|https://t.me/x]]")
        self.assertEqual(r.parsed_text, 'Salom <a href="https://a.uz">sayt</a>')
        self.assertEqual(r.buttons_json, [{"text": "Kanal", "url": "https://t.me/x"}])

    def test_draft_is_not_sent_and_ready_is_sent_in_batches(self):
        from django.core.management import call_command
        draft = Reklama.objects.create(admin_user_id=10, message_type="text", text="x", status="draft",
                                       source_chat_id=10, source_message_id=5)
        fake_bot = mock.MagicMock()
        fake_bot.send_message.return_value.message_id = 77
        with mock.patch("main.management.commands.send_reklama.telebot.TeleBot", return_value=fake_bot), \
             mock.patch("main.management.commands.send_reklama.time.sleep"):
            call_command("send_reklama", "--loop")
            fake_bot.copy_message.assert_not_called()
            draft.status = "ready"
            draft.save()
            call_command("send_reklama", "--loop")
        draft.refresh_from_db()
        self.assertEqual(draft.status, "completed")
        self.assertEqual((draft.total_users, draft.sent_count), (4, 4))
        self.assertEqual(fake_bot.copy_message.call_count, 4)


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
                           "bot_state": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                                         "LOCATION": "bot-state-tests"}})
class BotRegistrationTests(TestCase):
    """Bot ichida ro'yxatdan o'tish oqimi (Telegram API mock qilinadi)."""

    def msg(self, text=None, **extra):
        from telebot import types
        data = {"message_id": 1, "date": 0, "chat": {"id": 55, "type": "private"},
                "from": {"id": 55, "is_bot": False, "first_name": "Ali"}}
        if text is not None:
            data["text"] = text
            if text.startswith("/"):
                data["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        data.update(extra)
        return types.Update.de_json({"update_id": 1, "message": data})

    def callback(self, data):
        from telebot import types
        return types.Update.de_json({"update_id": 2, "callback_query": {
            "id": "1", "chat_instance": "1", "data": data, "from": {"id": 55, "is_bot": False, "first_name": "Ali"},
            "message": {"message_id": 9, "date": 0, "chat": {"id": 55, "type": "private"}}}})

    def test_full_registration(self):
        from main import bot as botmod
        with mock.patch.object(botmod.bot, "send_message") as send, \
             mock.patch.object(botmod.bot, "edit_message_text"), mock.patch.object(botmod.bot, "delete_message"), \
             mock.patch.object(botmod.bot, "answer_callback_query"), \
             mock.patch.object(botmod, "check_user_membership", return_value=(True, [])):
            send.return_value = mock.MagicMock(message_id=7)
            botmod.bot.threaded = False
            for update in [self.msg("/register"), self.msg("Ali"), self.msg("Valiyev"), self.msg("Karimovich"),
                           self.msg(contact={"phone_number": "998901112233", "first_name": "Ali", "user_id": 55}),
                           self.callback("region:Andijon"), self.callback("district:Asaka")]:
                botmod.bot.process_new_updates([update])
        user = TelegramUser.objects.get(telegram_id=55)
        self.assertEqual((user.name, user.surname, user.phone, user.district), ("Ali", "Valiyev", "+998901112233", "Asaka"))
        self.assertFalse(botmod.in_registration(55))


BOT_STATE_LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
                    "bot_state": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                                  "LOCATION": "bot-state-tests-2"}}


class MembershipCheckTests(TestCase):
    """Majburiy obuna: bot tekshira olmagan kanal hammani to'sib qo'ymasligi kerak."""

    def setUp(self):
        from main.models import RequiredChannel
        self.channel = RequiredChannel.objects.create(channel_id=-100123, channel_username="@kanal")

    def check(self, side_effect=None, status="member", **member):
        from main import bot as botmod
        result = mock.MagicMock(status=status, **member)
        with mock.patch.object(botmod.bot, "get_chat_member", side_effect=side_effect, return_value=result), \
             mock.patch.object(botmod, "_channel_check_failed") as failed:
            ok, not_joined = botmod.check_user_membership(5)
        return ok, not_joined, failed

    def api_error(self, description):
        from telebot.apihelper import ApiTelegramException
        return ApiTelegramException("getChatMember", None, {"error_code": 400, "description": description})

    def test_member_and_left(self):
        self.assertTrue(self.check(status="member")[0])
        self.assertTrue(self.check(status="administrator")[0])
        self.assertFalse(self.check(status="left")[0])
        self.assertFalse(self.check(status="kicked")[0])

    def test_restricted_member_counts(self):
        self.assertTrue(self.check(status="restricted", is_member=True)[0])
        self.assertFalse(self.check(status="restricted", is_member=False)[0])

    def test_user_not_found_means_not_joined(self):
        ok, not_joined, failed = self.check(side_effect=self.api_error("Bad Request: user not found"))
        self.assertFalse(ok)
        failed.assert_not_called()

    def test_bot_not_admin_does_not_block_users(self):
        ok, _, failed = self.check(side_effect=self.api_error("Bad Request: member list is inaccessible"))
        self.assertTrue(ok)
        failed.assert_called_once()


class ReklamaDeliveryTests(TestCase):
    def make(self, text, message_type="text"):
        return Reklama.objects.create(admin_user_id=10, message_type=message_type, text=text, status="draft",
                                      source_chat_id=10, source_message_id=5)

    def test_plain_message_is_copied(self):
        from main.reklama import deliver
        bot = mock.MagicMock()
        deliver(bot, self.make("<b>Salom</b>"), 7)
        bot.copy_message.assert_called_once()
        self.assertNotIn("caption", bot.copy_message.call_args.kwargs)
        bot.send_message.assert_not_called()

    def test_markup_text_is_sent_parsed(self):
        from main.reklama import deliver
        bot = mock.MagicMock()
        deliver(bot, self.make("Salom [[sayt](https://a.uz)]\n[[Kanal|https://t.me/x?a=1&amp;b=2]]"), 7)
        bot.copy_message.assert_not_called()
        args, kwargs = bot.send_message.call_args
        self.assertEqual(args[1], 'Salom <a href="https://a.uz">sayt</a>')
        button = kwargs["reply_markup"].keyboard[0][0]
        self.assertEqual(button.url, "https://t.me/x?a=1&b=2")

    def test_markup_caption_overrides_copy(self):
        from main.reklama import deliver
        bot = mock.MagicMock()
        deliver(bot, self.make("Rasm [[Kanal|https://t.me/x]]", "image"), 7)
        self.assertEqual(bot.copy_message.call_args.kwargs["caption"], "Rasm")

    def test_blocked_user_marked_inactive(self):
        from telebot.apihelper import ApiTelegramException
        from main.reklama import send_reklama
        user = TelegramUser.objects.create(telegram_id=99, name="U", surname="S", phone="+998901234567",
                                           region="Toshkent", district="Chinoz")
        bot = mock.MagicMock()
        bot.copy_message.side_effect = ApiTelegramException(
            "copyMessage", None, {"error_code": 403, "description": "Forbidden: bot was blocked by the user"})
        self.assertFalse(send_reklama(bot, self.make("x"), user))
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_rate_limit_retried(self):
        from telebot.apihelper import ApiTelegramException
        from main.reklama import send_reklama
        user = TelegramUser.objects.create(telegram_id=98, name="U", surname="S", phone="+998901234567",
                                           region="Toshkent", district="Chinoz")
        bot = mock.MagicMock()
        bot.copy_message.side_effect = [ApiTelegramException(
            "copyMessage", None, {"error_code": 429, "description": "Too Many Requests",
                                  "parameters": {"retry_after": 1}}), None]
        with mock.patch("main.reklama.time.sleep"):
            self.assertTrue(send_reklama(bot, self.make("x"), user))
        self.assertEqual(bot.copy_message.call_count, 2)


@override_settings(CACHES=BOT_STATE_LOCMEM)
class ReklamaCommandRecoveryTests(TestCase):
    def test_stuck_sending_is_resumed(self):
        from django.core.management import call_command
        TelegramUser.objects.create(telegram_id=1, name="U", surname="S", phone="+998901234567",
                                    region="Toshkent", district="Chinoz")
        r = Reklama.objects.create(admin_user_id=10, message_type="text", text="x", status="sending",
                                   source_chat_id=10, source_message_id=5, total_users=1)
        fake_bot = mock.MagicMock()
        fake_bot.send_message.return_value.message_id = 77
        with mock.patch("main.management.commands.send_reklama.telebot.TeleBot", return_value=fake_bot), \
             mock.patch("main.management.commands.send_reklama.time.sleep"):
            call_command("send_reklama", "--loop")
        r.refresh_from_db()
        self.assertEqual((r.status, r.sent_count), ("completed", 1))

    def test_second_process_does_not_run_while_locked(self):
        from django.core.management import call_command
        from main.state import acquire_lock, release_lock
        Reklama.objects.create(admin_user_id=10, message_type="text", text="x", status="ready",
                               source_chat_id=10, source_message_id=5)
        self.assertTrue(acquire_lock("send_reklama", 60))
        try:
            with mock.patch("main.management.commands.send_reklama.telebot.TeleBot") as tb:
                call_command("send_reklama")
                tb.assert_not_called()
        finally:
            release_lock("send_reklama")


@override_settings(TELEGRAM_BOT_TOKEN=TOKEN)
class LegacyInitDataTests(TestCase):
    def test_signed(self):
        from main.views import decode_init_data
        self.assertEqual(decode_init_data(init_data(42))["user"]["id"], 42)

    def test_unsigned_with_special_chars(self):
        from urllib.parse import quote, urlencode
        from main.views import decode_init_data
        raw = urlencode({"user": json.dumps({"id": 7, "first_name": "A&B=C+D"}), "auth_date": "1", "hash": "x"})
        self.assertEqual(decode_init_data(raw)["user"]["first_name"], "A&B=C+D")
        self.assertEqual(decode_init_data(quote(raw))["user"]["id"], 7)

    def test_dict_and_garbage(self):
        from main.views import decode_init_data, find_user
        self.assertEqual(decode_init_data({"user": {"id": 3}})["user"]["id"], 3)
        self.assertIsNone(decode_init_data("")["user"])
        self.assertIsNone(decode_init_data("user=%7Bbad")["user"])
        self.assertIsNone(find_user("undefined"))


@override_settings(TELEGRAM_BOT_TOKEN=TOKEN, WEBAPP_DEV_TELEGRAM_ID=None)
class WebAppRobustnessTests(TestCase):
    def test_auth_works_without_csrf_cookie(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        r = client.post(reverse("webapp:auth"), {"init_data": init_data(5), "next": "/"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

    def test_phone_normalized(self):
        from webapp.forms import RegisterForm
        base = {"name": "A", "surname": "B", "father_name": "C", "region": "Andijon", "district": "Asaka"}
        for raw in ["+998 90 123-45-67", "998901234567", "901234567"]:
            form = RegisterForm({**base, "phone": raw})
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.cleaned_data["phone"], "+998901234567")
        self.assertFalse(RegisterForm({**base, "phone": "+99890"}).is_valid())

    def test_csrf_failure_page(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        r = client.post(reverse("webapp:register"), {})
        self.assertEqual(r.status_code, 403)
        self.assertContains(r, "Sahifa eskirgan", status_code=403)


@override_settings(TELEGRAM_BOT_TOKEN=TOKEN, WEBAPP_DEV_TELEGRAM_ID=None, MEDIA_ROOT=TEST_MEDIA)
class WebAppSubscriptionTests(TestCase):
    """Majburiy kanaldan chiqqan foydalanuvchi WebApp'ni umuman ishlata olmaydi."""

    def setUp(self):
        from main.models import RequiredChannel
        RequiredChannel.objects.create(channel_id=-100555, channel_username="@majburiy")
        TelegramUser.objects.create(telegram_id=111, name="Ali", surname="V", father_name="X",
                                    phone="+998901234567", region="Toshkent", district="Chinoz")
        self.client.post(reverse("webapp:auth"), {"init_data": init_data(111), "next": "/"})

    def member(self, status):
        from main import bot as botmod
        return mock.patch.object(botmod.bot, "get_chat_member", return_value=mock.MagicMock(status=status))

    def test_not_subscribed_blocked_everywhere(self):
        with self.member("left"):
            for name in ["webapp:home", "webapp:profile", "webapp:send_test", "webapp:dtm", "webapp:register"]:
                r = self.client.get(reverse(name))
                self.assertEqual(r.status_code, 403, name)
                self.assertTemplateUsed(r, "webapp/subscribe.html")
                self.assertContains(r, "https://t.me/majburiy", status_code=403)

    def test_subscribed_allowed(self):
        with self.member("member"):
            self.assertEqual(self.client.get(reverse("webapp:home")).status_code, 200)

    def test_leaving_channel_blocks_post_immediately(self):
        with self.member("member"):
            self.assertEqual(self.client.get(reverse("webapp:home")).status_code, 200)
        with self.member("left"):
            # sahifa ochish 1 daqiqa eslab qolinadi, lekin ma'lumot yuborish darhol to'xtatiladi
            r = self.client.post(reverse("webapp:register"), {"name": "X"})
            self.assertEqual(r.status_code, 403)
            self.assertTemplateUsed(r, "webapp/subscribe.html")
            # keyingi sahifa ham endi bloklangan (eslab qolingan natija o'chirildi)
            self.assertEqual(self.client.get(reverse("webapp:home")).status_code, 403)

    def test_recheck_after_cache_expires(self):
        with self.member("member"):
            self.client.get(reverse("webapp:home"))
        session = self.client.session
        session["tg_subscribed_until"] = 0
        session.save()
        from django.conf import settings as dj_settings
        self.client.cookies[dj_settings.SESSION_COOKIE_NAME] = session.session_key  # cookie sessiya
        with self.member("left"):
            self.assertEqual(self.client.get(reverse("webapp:home")).status_code, 403)


class ApiClosedTests(TestCase):
    def test_anonymous_rejected(self):
        TelegramUser.objects.create(telegram_id=1, name="A", surname="B", phone="+998901234567",
                                    region="Toshkent", district="Chinoz")
        for method, url in [("get", "/api/users/"), ("get", "/api/users/1/"), ("delete", "/api/users/1/"),
                            ("post", "/api/users/"), ("get", "/api/tests/"), ("get", "/swagger/")]:
            r = getattr(self.client, method)(url)
            self.assertIn(r.status_code, (401, 403), f"{method} {url}")
        self.assertTrue(TelegramUser.objects.filter(telegram_id=1).exists())

    def test_staff_allowed(self):
        from django.contrib.auth.models import User
        User.objects.create_superuser("admin", "a@a.uz", "parol12345")
        self.client.login(username="admin", password="parol12345")
        self.assertEqual(self.client.get("/api/users/").status_code, 200)


class ErrorLogTests(TestCase):
    def setUp(self):
        from main import errorlog
        self.errorlog = errorlog
        self.path = TEST_MEDIA + "/errors.json"
        self.override = override_settings(ERROR_LOG_FILE=self.path, ERROR_LOG_KEY="maxfiy-kalit-123",
                                          GITHUB_ERRORS_TOKEN=None)
        self.override.enable()
        errorlog.clear_errors()
        errorlog._last_write.clear()
        errorlog._pending.clear()

    def tearDown(self):
        self.override.disable()

    def raise_and_log(self, msg="boom"):
        import logging
        try:
            {}["yoq"]
        except KeyError:
            logging.getLogger("main.test").exception(msg)

    def test_sanitize(self):
        s = self.errorlog.sanitize("tel +998 90 123 45 67, id 5021533207, a@b.uz, 123456:" + "A" * 35)
        for leaked in ["5021533207", "a@b.uz", "AAAA", "123 45 67"]:
            self.assertNotIn(leaked, s)

    def test_duplicates_grouped(self):
        self.raise_and_log()
        self.errorlog._last_write.clear()  # yozish oralig'ini kutmaslik uchun
        self.raise_and_log()
        data = self.errorlog.load_errors()
        self.assertEqual(len(data), 1)
        entry = next(iter(data.values()))
        self.assertEqual((entry["type"], entry["count"]), ("KeyError", 2))
        self.assertIn("webapp/tests.py", entry["location"])

    def test_storm_is_throttled(self):
        for _ in range(50):
            self.raise_and_log()
        self.assertEqual(next(iter(self.errorlog.load_errors().values()))["count"], 1)  # qolgani keyin yoziladi
        self.errorlog._last_write.clear()
        self.raise_and_log()
        self.assertEqual(next(iter(self.errorlog.load_errors().values()))["count"], 51)

    def test_endpoint_requires_key(self):
        self.raise_and_log()
        self.assertEqual(self.client.get("/_errors/").status_code, 404)
        self.assertEqual(self.client.get("/_errors/?key=notogri").status_code, 404)
        r = self.client.get("/_errors/?key=maxfiy-kalit-123&text=1")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "KeyError")

    def test_api(self):
        self.raise_and_log()
        self.assertEqual(self.client.get("/api/errors/").status_code, 404)
        r = self.client.get("/api/errors/", HTTP_AUTHORIZATION="Bearer maxfiy-kalit-123")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["total_kinds"], 1)
        fp = body["errors"][0]["fingerprint"]
        self.assertIn("KeyError", body["errors"][0]["traceback"])
        # bitta xato, keyin "tuzatildi" deb o'chirish
        self.assertEqual(self.client.get(f"/api/errors/{fp}/?key=maxfiy-kalit-123").json()["type"], "KeyError")
        self.assertEqual(self.client.delete(f"/api/errors/{fp}/", HTTP_X_ERROR_LOG_KEY="maxfiy-kalit-123")
                         .json()["removed"], 1)
        self.assertEqual(self.client.get("/api/errors/?key=maxfiy-kalit-123").json()["total_kinds"], 0)
        # since: kelajakdagi vaqt — hech narsa qaytmaydi
        self.raise_and_log()
        self.assertEqual(self.client.get("/api/errors/?key=maxfiy-kalit-123&since=9999999999").json()["returned"], 0)

    def test_api_disabled_without_key_setting(self):
        with override_settings(ERROR_LOG_KEY=None):
            self.assertEqual(self.client.get("/api/errors/?key=").status_code, 404)

    def test_bot_handler_exception_is_logged(self):
        from main import bot as botmod
        try:
            raise ValueError("handler buzildi")
        except ValueError as e:
            botmod._LogHandlerErrors().handle(e)
        self.assertTrue(any(e["type"] == "ValueError" for e in self.errorlog.load_errors().values()))

    def test_clear(self):
        self.raise_and_log()
        self.assertEqual(self.errorlog.clear_errors(), 1)
        self.assertEqual(self.errorlog.load_errors(), {})


class CleanupTests(TestCase):
    def test_finished_reklama_rows_removed(self):
        from django.core.management import call_command
        u = TelegramUser.objects.create(telegram_id=1, name="U", surname="S", phone="+998901234567",
                                        region="Toshkent", district="Chinoz")
        done = Reklama.objects.create(admin_user_id=1, message_type="text", text="x", status="completed")
        active = Reklama.objects.create(admin_user_id=1, message_type="text", text="y", status="pending")
        done.sending_users.add(u)
        active.sending_users.add(u)
        call_command("cleanup")
        self.assertEqual(done.sending_users.count(), 0)
        self.assertEqual(active.sending_users.count(), 1)  # yuborilayotganga tegmaydi
        self.assertTrue(TelegramUser.objects.filter(pk=u.pk).exists())
