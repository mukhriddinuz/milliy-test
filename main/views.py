import json
import urllib.parse
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from django_filters.rest_framework import DjangoFilterBackend
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .logger_send import log_to_telegram
from .models import BlockTest, BookTest, RequiredChannel, Subject, TelegramUser, Test
from .serializers import (
    BlockTestResultResponseSerializer, BlockTestSerializer,
    BookTestCheckAnswerSerializer, BookTestCreateSerializer, BookTestSerializer,
    RequiredChannelListSerializer, RequiredChannelSerializer,
    SubjectListSerializer, SubjectSerializer,
    TelegramUserListSerializer, TelegramUserSerializer,
    TestListSerializer, TestSerializer,
)
from .services import (
    SubmissionError, notify_block_test_created, notify_booktest_created, notify_test_created,
    submit_block_test, submit_booktest, submit_test_answers,
)


def decode_init_data(init_data: str):

    # 1. URL decode
    decoded = urllib.parse.unquote(init_data)

    # 2. Query stringni dict qilish
    parsed = urllib.parse.parse_qs(decoded)

    # 3. user JSON qismi query stringda emas, balki decodedning boshida turgan bo‘lishi mumkin
    # uni ajratish uchun "}" belgisi qayerda tugashini topamiz
    user_json_str = None
    if decoded.startswith("{"):  # to‘g‘ridan-to‘g‘ri JSON bo‘lsa
        end_index = decoded.find("}") + 1
        user_json_str = decoded[:end_index]
    else:
        if "user" in parsed:
            user_json_str = parsed["user"][0]

    user_data = json.loads(user_json_str) if user_json_str else None

    return {
        "user": user_data,
        "chat_instance": parsed.get("chat_instance", [None])[0],
        "chat_type": parsed.get("chat_type", [None])[0],
        "auth_date": parsed.get("auth_date", [None])[0],
        "signature": parsed.get("signature", [None])[0],
        "hash": parsed.get("hash", [None])[0],
    }
    

class TelegramUserViewSet(viewsets.ModelViewSet):
    """
    Telegram foydalanuvchilarni boshqarish uchun API
    """
    queryset = TelegramUser.objects.all()
    serializer_class = TelegramUserSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_active', 'is_banned', 'region']
    search_fields = ['name', 'surname', 'username', 'phone']
    ordering_fields = ['created_at', 'balance', 'name']
    ordering = ['-created_at']
    lookup_field = "telegram_id" # telegram_id bo'yicha qidirish
    
    def get_serializer_class(self):
        if self.action == 'list':
            return TelegramUserListSerializer
        return TelegramUserSerializer
    
    @swagger_auto_schema(
        operation_summary="Barcha foydalanuvchilar ro'yxati",
        operation_description="Tizimda ro'yxatdan o'tgan barcha Telegram foydalanuvchilarining ro'yxatini olish. Filtrlash, qidiruv va tartiblash imkoniyatlari mavjud.",
        responses={
            200: TelegramUserListSerializer(many=True),
        }
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_summary="Yangi foydalanuvchi yaratish",
        operation_description="Tizimga yangi Telegram foydalanuvchisini qo'shish. Barcha majburiy maydonlarni to'ldirish kerak.",
        request_body=TelegramUserSerializer,
        responses={
            201: TelegramUserSerializer,
            400: 'Noto\'g\'ri ma\'lumotlar'
        }
    )
    def create(self, request, *args, **kwargs):
        """Eski tizimdagidek: telegram_id mavjud bo'lsa ma'lumotlar yangilanadi (upsert)."""
        instance = TelegramUser.objects.filter(telegram_id=request.data.get("telegram_id")).first()
        serializer = self.get_serializer(instance, data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        if instance is None:
            log_to_telegram("users", "👤 <b>Yangi foydalanuvchi yaratildi</b>", request=request, user=user)
        return Response(TelegramUserSerializer(user).data,
                        status=status.HTTP_200_OK if instance else status.HTTP_201_CREATED)
    
    @swagger_auto_schema(
        operation_summary="Foydalanuvchi ma'lumotlarini ko'rish",
        operation_description="Bitta foydalanuvchining to'liq ma'lumotlarini olish.",
        responses={
            200: TelegramUserSerializer,
            404: 'Foydalanuvchi topilmadi'
        }
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_summary="Foydalanuvchi ma'lumotlarini to'liq yangilash",
        operation_description="Foydalanuvchining barcha ma'lumotlarini yangilash. Barcha maydonlarni yuborish kerak.",
        request_body=TelegramUserSerializer,
        responses={
            200: TelegramUserSerializer,
            400: 'Noto\'g\'ri ma\'lumotlar',
            404: 'Foydalanuvchi topilmadi'
        }
    )
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_summary="Foydalanuvchi ma'lumotlarini qisman yangilash",
        operation_description="Foydalanuvchining faqat kerakli maydonlarini yangilash. Faqat o'zgartirmoqchi bo'lgan maydonlarni yuborish kifoya.",
        request_body=TelegramUserSerializer,
        responses={
            200: TelegramUserSerializer,
            400: 'Noto\'g\'ri ma\'lumotlar',
            404: 'Foydalanuvchi topilmadi'
        }
    )
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_summary="Foydalanuvchini o'chirish",
        operation_description="Foydalanuvchini tizimdan butunlay o'chirish. Bu amal qaytarib bo'lmaydi!",
        responses={
            204: 'Muvaffaqiyatli o\'chirildi',
            404: 'Foydalanuvchi topilmadi'
        }
    )
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_summary="Foydalanuvchini bloklash",
        operation_description="Foydalanuvchini tizimdan vaqtincha bloklash. Bloklangan foydalanuvchi botdan foydalana olmaydi.",
        responses={200: 'Foydalanuvchi muvaffaqiyatli bloklandi'}
    )
    @action(detail=True, methods=['post'])
    def ban_user(self, request, pk=None):
        """Foydalanuvchini bloklash"""
        user = self.get_object()
        user.is_banned = True
        user.save()
        return Response({'status': 'Foydalanuvchi muvaffaqiyatli bloklandi'})
    
    @swagger_auto_schema(
        operation_summary="Foydalanuvchi blokini bekor qilish",
        operation_description="Bloklangan foydalanuvchining blokini olib tashlash. Foydalanuvchi yana botdan foydalana oladi.",
        responses={200: 'Foydalanuvchi bloki muvaffaqiyatli bekor qilindi'}
    )
    @action(detail=True, methods=['post'])
    def unban_user(self, request, pk=None):
        """Foydalanuvchi blokini bekor qilish"""
        user = self.get_object()
        user.is_banned = False
        user.save()
        return Response({'status': 'Foydalanuvchi bloki muvaffaqiyatli bekor qilindi'})
    
    @swagger_auto_schema(
        operation_summary="Foydalanuvchi balansini yangilash",
        operation_description="Foydalanuvchining hisob balansiga pul qo'shish yoki ayirish. Musbat son qo'shadi, manfiy son ayiradi.",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'amount': openapi.Schema(type=openapi.TYPE_NUMBER, description='Qo\'shiladigan yoki ayiriladigan summa'),
            },
            required=['amount']
        ),
        responses={
            200: openapi.Response(
                'Balans muvaffaqiyatli yangilandi',
                openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'status': openapi.Schema(type=openapi.TYPE_STRING),
                        'new_balance': openapi.Schema(type=openapi.TYPE_NUMBER),
                    }
                )
            ),
            400: 'Noto\'g\'ri ma\'lumot'
        }
    )
    @action(detail=True, methods=['post'])
    def update_balance(self, request, pk=None):
        """Foydalanuvchi balansini yangilash"""
        user = self.get_object()
        amount = request.data.get('amount')
        
        if amount is None:
            return Response(
                {'error': 'Summa kiritish majburiy'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            user.balance += Decimal(str(amount))
            user.save(update_fields=['balance', 'updated_at'])
            return Response({
                'status': 'Balans muvaffaqiyatli yangilandi',
                'new_balance': user.balance
            })
        except (InvalidOperation, ValueError):
            return Response(
                {'error': 'Noto\'g\'ri summa formati'}, 
                status=status.HTTP_400_BAD_REQUEST
            )


class SubjectViewSet(viewsets.ModelViewSet):
    """
    Fanlarni boshqarish uchun API
    """
    queryset = Subject.objects.all()
    serializer_class = SubjectSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_active']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']
    
    def get_serializer_class(self):
        if self.action == 'list':
            return SubjectListSerializer
        return SubjectSerializer
    
    @swagger_auto_schema(
        operation_summary="Barcha fanlar ro'yxati",
        operation_description="Tizimdagi barcha fanlarning ro'yxatini olish. Har bir fan nechta test borligini ko'rsatadi.",
        responses={
            200: SubjectListSerializer(many=True),
        }
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_summary="Yangi fan yaratish",
        operation_description="Tizimga yangi fan qo'shish. Fan nomi noyob bo'lishi kerak.",
        request_body=SubjectSerializer,
        responses={
            201: SubjectSerializer,
            400: 'Noto\'g\'ri ma\'lumotlar yoki fan nomi allaqachon mavjud'
        }
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_summary="Fan ma'lumotlarini ko'rish",
        operation_description="Bitta fanning to'liq ma'lumotlarini va unga tegishli testlar sonini olish.",
        responses={
            200: SubjectSerializer,
            404: 'Fan topilmadi'
        }
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_summary="Fan ma'lumotlarini to'liq yangilash",
        operation_description="Fanning barcha ma'lumotlarini yangilash. Barcha maydonlarni yuborish kerak.",
        request_body=SubjectSerializer,
        responses={
            200: SubjectSerializer,
            400: 'Noto\'g\'ri ma\'lumotlar',
            404: 'Fan topilmadi'
        }
    )
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_summary="Fan ma'lumotlarini qisman yangilash",
        operation_description="Fanning faqat kerakli maydonlarini yangilash. Faqat o'zgartirmoqchi bo'lgan maydonlarni yuborish kifoya.",
        request_body=SubjectSerializer,
        responses={
            200: SubjectSerializer,
            400: 'Noto\'g\'ri ma\'lumotlar',
            404: 'Fan topilmadi'
        }
    )
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_summary="Fanni o'chirish",
        operation_description="Fanni tizimdan butunlay o'chirish. Bu amal unga tegishli barcha testlarni ham o'chiradi!",
        responses={
            204: 'Muvaffaqiyatli o\'chirildi',
            404: 'Fan topilmadi'
        }
    )
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_summary="Fanga tegishli testlarni ko'rish",
        operation_description="Bitta fanga tegishli barcha testlarning ro'yxatini olish.",
        responses={200: TestListSerializer(many=True)}
    )
    @action(detail=True, methods=['get'])
    def tests(self, request, pk=None):
        """Fanga tegishli barcha testlarni olish"""
        subject = self.get_object()
        tests = subject.tests.all()
        serializer = TestListSerializer(tests, many=True)
        return Response(serializer.data)
    
    @swagger_auto_schema(
        operation_summary="Fan holatini o'zgartirish",
        operation_description="Fanni faol yoki nofaol holatiga o'tkazish. Nofaol fanlar foydalanuvchilarga ko'rinmaydi.",
        responses={200: 'Fan holati muvaffaqiyatli o\'zgartirildi'}
    )
    @action(detail=True, methods=['post'])
    def toggle_active(self, request, pk=None):
        """Fan holatini o'zgartirish"""
        subject = self.get_object()
        subject.is_active = not subject.is_active
        subject.save()
        return Response({
            'status': f"Fan {'faol' if subject.is_active else 'nofaol'} qilindi",
            'is_active': subject.is_active
        })


class TestViewSet(viewsets.ModelViewSet):
    """
    Testlarni boshqarish uchun API
    """
    queryset = Test.objects.all()
    serializer_class = TestSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['subject', 'creator', 'is_active', 'is_public']
    search_fields = ['title', 'subject__name', 'creator__name']
    ordering_fields = ['created_at', 'title', 'questions_count']
    ordering = ['-created_at']
    
    def get_serializer_class(self):
        if self.action == 'list':
            return TestListSerializer
        return TestSerializer
    
    @swagger_auto_schema(
        operation_summary="Barcha testlar ro'yxati",
        operation_description="Tizimdagi barcha testlarning ro'yxatini olish. Filtrlash va qidiruv imkoniyatlari mavjud.",
        responses={
            200: TestListSerializer(many=True),
        }
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_summary="Yangi test yaratish",
        operation_description="Tizimga yangi test qo'shish. Fan va yaratuvchini ko'rsatish majburiy.",
        request_body=TestSerializer,
        responses={
            201: TestSerializer,
            400: 'Noto\'g\'ri ma\'lumotlar'
        }
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        notify_test_created(instance)

        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)
    
    @swagger_auto_schema(
        operation_summary="Test ma'lumotlarini ko'rish",
        operation_description="Bitta testning to'liq ma'lumotlari va javoblarini olish.",
        responses={
            200: TestSerializer,
            404: 'Test topilmadi'
        }
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_summary="Test ma'lumotlarini to'liq yangilash",
        operation_description="Testning barcha ma'lumotlarini yangilash. Barcha maydonlarni yuborish kerak.",
        request_body=TestSerializer,
        responses={
            200: TestSerializer,
            400: 'Noto\'g\'ri ma\'lumotlar',
            404: 'Test topilmadi'
        }
    )
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_summary="Test ma'lumotlarini qisman yangilash",
        operation_description="Testning faqat kerakli maydonlarini yangilash. Faqat o'zgartirmoqchi bo'lgan maydonlarni yuborish kifoya.",
        request_body=TestSerializer,
        responses={
            200: TestSerializer,
            400: 'Noto\'g\'ri ma\'lumotlar',
            404: 'Test topilmadi'
        }
    )
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_summary="Testni o'chirish",
        operation_description="Testni tizimdan butunlay o'chirish. Bu amal qaytarib bo'lmaydi!",
        responses={
            204: 'Muvaffaqiyatli o\'chirildi',
            404: 'Test topilmadi'
        }
    )
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)
    
    def get_queryset(self):
        queryset = Test.objects.select_related('subject', 'creator')
        
        # Filter by subject if provided
        subject_id = self.request.query_params.get('subject_id')
        if subject_id:
            queryset = queryset.filter(subject_id=subject_id)
        
        # Filter by creator if provided
        creator_id = self.request.query_params.get('creator_id')
        if creator_id:
            queryset = queryset.filter(creator_id=creator_id)
        
        # Filter public tests only
        public_only = self.request.query_params.get('public_only')
        if public_only and public_only.lower() == 'true':
            queryset = queryset.filter(is_public=True)
        
        return queryset
    
    @swagger_auto_schema(
        operation_summary="Test holatini o'zgartirish",
        operation_description="Testni faol yoki nofaol holatiga o'tkazish. Nofaol testlar foydalanuvchilarga ko'rinmaydi.",
        responses={200: 'Test holati muvaffaqiyatli o\'zgartirildi'}
    )
    @action(detail=True, methods=['post'])
    def toggle_active(self, request, pk=None):
        """Test holatini o'zgartirish"""
        test = self.get_object()
        test.is_active = not test.is_active
        test.save()
        return Response({
            'status': f"Test {'faol' if test.is_active else 'nofaol'} qilindi",
            'is_active': test.is_active
        })
    
    @swagger_auto_schema(
        operation_summary="Test ommaviyligini o'zgartirish",
        operation_description="Testni hamma uchun ochiq yoki faqat ma'lum foydalanuvchilar uchun qilish.",
        responses={200: 'Test ommaviylik holati muvaffaqiyatli o\'zgartirildi'}
    )
    @action(detail=True, methods=['post'])
    def toggle_public(self, request, pk=None):
        """Test ommaviyligini o'zgartirish"""
        test = self.get_object()
        test.is_public = not test.is_public
        test.save()
        return Response({
            'status': f"Test {'ochiq' if test.is_public else 'yopiq'} qilindi",
            'is_public': test.is_public
        })
    
    @swagger_auto_schema(
        operation_summary="Test javoblarini o'rnatish",
        operation_description="Test uchun to'g'ri javoblarni JSON formatida o'rnatish. Javoblar 'savol_raqami': 'javob' formatida bo'lishi kerak.",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'answers': openapi.Schema(
                    type=openapi.TYPE_OBJECT, 
                    description='To\'g\'ri javoblar JSON formatida',
                    example={"1": "A", "2": "B", "3": "C"}
                ),
            },
            required=['answers']
        ),
        responses={
            200: 'Javoblar muvaffaqiyatli yangilandi',
            400: 'Javoblar kiritish majburiy'
        }
    )
    @action(detail=True, methods=['post'])
    def set_answers(self, request, pk=None):
        """Test uchun to'g'ri javoblarni o'rnatish"""
        test = self.get_object()
        answers = request.data.get('answers')
        
        if not answers:
            return Response(
                {'error': 'Javoblar kiritish majburiy'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        test.answers = answers
        test.save()
        return Response({
            'status': 'Javoblar muvaffaqiyatli yangilandi',
            'answers': test.answers
        })
    
    @swagger_auto_schema(
        operation_summary="Ommaviy testlarni ko'rish",
        operation_description="Hamma uchun ochiq va faol bo'lgan barcha testlarning ro'yxatini olish.",
        responses={200: TestListSerializer(many=True)}
    )
    @action(detail=False, methods=['get'])
    def public_tests(self, request):
        """Barcha ommaviy testlarni olish"""
        tests = self.get_queryset().filter(is_public=True, is_active=True)
        serializer = self.get_serializer(tests, many=True)
        return Response(serializer.data)
    
    @swagger_auto_schema(
        operation_summary="Fan bo'yicha guruhlangan testlar",
        operation_description="Barcha faol testlarni fan bo'yicha guruhlangan holda olish. Har bir fan nomi ostida unga tegishli testlar ko'rsatiladi.",
        responses={
            200: openapi.Response(
                'Fan bo\'yicha guruhlangan testlar',
                openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    additional_properties=openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_OBJECT)
                    )
                )
            )
        }
    )
    @action(detail=False, methods=['get'])
    def by_subject(self, request):
        """Testlarni fan bo'yicha guruhlangan holda olish"""
        tests = self.get_queryset().filter(is_active=True)
        grouped_tests = defaultdict(list)

        for test in tests:
            test_data = TestListSerializer(test).data
            grouped_tests[test.subject.name].append(test_data)
        
        return Response(dict(grouped_tests))
    
    @swagger_auto_schema(
        operation_summary="Test javoblarini tekshirish",
        operation_description="Foydalanuvchi kiritgan javoblarni testning to'g'ri javoblari bilan solishtirib, natijani qaytaradi.",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'user_answers': openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    description="Foydalanuvchi javoblari JSON formatida",
                    example={"1": "A", "2": "B", "3": "C"}
                ),
            },
            required=['user_answers']
        ),
        responses={
            200: openapi.Response(
                'Natija',
                openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'correct_count': openapi.Schema(type=openapi.TYPE_INTEGER),
                        'total_questions': openapi.Schema(type=openapi.TYPE_INTEGER),
                        'percentage': openapi.Schema(type=openapi.TYPE_NUMBER),
                        'details': openapi.Schema(type=openapi.TYPE_OBJECT)
                    }
                )
            ),
            400: 'Javoblar kiritish majburiy'
        }
    )
    @action(detail=True, methods=['post'])
    def check_answers(self, request, pk=None):
        
        """Foydalanuvchi javoblarini tekshirish va natijani saqlash"""
        test = self.get_object()
        user_answers = request.data.get('user_answers')
        
        if not user_answers:
            return Response(
                    {'error': 'Javoblar kiritish majburiy'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        if not isinstance(user_answers, dict):
            return Response(
                {'error': "Javoblar {\"1\": \"A\", ...} ko'rinishida bo'lishi kerak"},
                status=status.HTTP_400_BAD_REQUEST
            )

        user_data = decode_init_data(request.data.get('init_data', '')).get('user') or {}
        if not user_data.get('id'):
            return Response(
                {'error': "Telegram foydalanuvchi ma'lumotlari (init_data) topilmadi"},
                status=status.HTTP_400_BAD_REQUEST
            )
        telegram_user = TelegramUser.objects.filter(telegram_id=user_data['id']).first()
        if telegram_user is None:
            return Response(
                {'error': "Avval botda ro'yxatdan o'ting"},
                status=status.HTTP_404_NOT_FOUND
            )

        try:
            result, test_result = submit_test_answers(test, telegram_user, user_answers, request=request)
        except SubmissionError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            **result,
            'test_result_id': test_result.id,
            'is_passed': test_result.is_passed,
            'passed_status': "✅ Testdan o'tdingiz" if test_result.is_passed else "❌ Testdan o'tolmadingiz",
        })


class RequiredChannelViewSet(viewsets.ModelViewSet):
    """
    Majburiy kanallarni boshqarish uchun API
    """
    queryset = RequiredChannel.objects.all()
    serializer_class = RequiredChannelSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_active']
    search_fields = ['channel_username']
    ordering_fields = ['created_at', 'channel_username']
    ordering = ['-created_at']
    
    def get_serializer_class(self):
        if self.action == 'list':
            return RequiredChannelListSerializer
        return RequiredChannelSerializer
    
    @swagger_auto_schema(
        operation_summary="Barcha majburiy kanallar ro'yxati",
        operation_description="Tizimdagi barcha majburiy kanallar ro'yxatini olish. Filtrlash va qidiruv imkoniyatlari mavjud.",
        responses={
            200: RequiredChannelListSerializer(many=True),
        }
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_summary="Yangi majburiy kanal qo'shish",
        operation_description="Tizimga yangi majburiy kanal qo'shish. Kanal ID si noyob bo'lishi kerak.",
        request_body=RequiredChannelSerializer,
        responses={
            201: RequiredChannelSerializer,
            400: 'Noto\'g\'ri ma\'lumotlar yoki kanal allaqachon mavjud'
        }
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_summary="Majburiy kanal ma'lumotlarini ko'rish",
        operation_description="Bitta majburiy kanalning to'liq ma'lumotlarini olish.",
        responses={
            200: RequiredChannelSerializer,
            404: 'Kanal topilmadi'
        }
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_summary="Majburiy kanal ma'lumotlarini to'liq yangilash",
        operation_description="Majburiy kanalning barcha ma'lumotlarini yangilash. Barcha maydonlarni yuborish kerak.",
        request_body=RequiredChannelSerializer,
        responses={
            200: RequiredChannelSerializer,
            400: 'Noto\'g\'ri ma\'lumotlar',
            404: 'Kanal topilmadi'
        }
    )
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_summary="Majburiy kanal ma'lumotlarini qisman yangilash",
        operation_description="Majburiy kanalning faqat kerakli maydonlarini yangilash. Faqat o'zgartirmoqchi bo'lgan maydonlarni yuborish kifoya.",
        request_body=RequiredChannelSerializer,
        responses={
            200: RequiredChannelSerializer,
            400: 'Noto\'g\'ri ma\'lumotlar',
            404: 'Kanal topilmadi'
        }
    )
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_summary="Majburiy kanalni o'chirish",
        operation_description="Majburiy kanalni tizimdan butunlay o'chirish.",
        responses={
            204: 'Muvaffaqiyatli o\'chirildi',
            404: 'Kanal topilmadi'
        }
    )
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)
    
    @swagger_auto_schema(
        operation_summary="Majburiy kanal holatini o'zgartirish",
        operation_description="Majburiy kanalni faol yoki nofaol holatiga o'tkazish.",
        responses={200: 'Kanal holati muvaffaqiyatli o\'zgartirildi'}
    )
    @action(detail=True, methods=['post'])
    def toggle_active(self, request, pk=None):
        """Majburiy kanal holatini o'zgartirish"""
        channel = self.get_object()
        channel.is_active = not channel.is_active
        channel.save()
        return Response({
            'status': f"Kanal {'faol' if channel.is_active else 'nofaol'} qilindi",
            'is_active': channel.is_active
        })


# ---------------------------------------------------------------------------
# Kitob testlari: /api/booktests/<slug>/
# ---------------------------------------------------------------------------

class BookTestViewSet(viewsets.ModelViewSet):
    queryset = BookTest.objects.select_related("subject", "creator")
    lookup_field = "slug"
    lookup_url_kwarg = "slug"

    def get_serializer_class(self):
        if self.action == "create":
            return BookTestCreateSerializer
        if self.action == "check":
            return BookTestCheckAnswerSerializer
        return BookTestSerializer

    @swagger_auto_schema(
        operation_summary="Yangi kitob test yaratish",
        operation_description="'scores' — har bir savol bali (answers bilan bir xil uzunlikda).",
        request_body=BookTestCreateSerializer, responses={201: BookTestSerializer},
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        test = serializer.save()
        notify_booktest_created(test)
        return Response(BookTestSerializer(test).data, status=status.HTTP_201_CREATED)

    @swagger_auto_schema(
        operation_summary="Kitob test javoblarini tekshirish",
        request_body=BookTestCheckAnswerSerializer,
        responses={200: "Natija (correct, total, percentage, score, passed, ...)", 400: "Xatolik"},
    )
    @action(detail=True, methods=["post"])
    def check(self, request, slug=None):
        test = self.get_object()
        serializer = BookTestCheckAnswerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = TelegramUser.objects.filter(telegram_id=serializer.validated_data["telegram_id"]).first()
        if user is None:
            return Response({"error": "Foydalanuvchi topilmadi"}, status=status.HTTP_404_NOT_FOUND)
        try:
            result, grade, _ = submit_booktest(
                test, user, serializer.validated_data["answers"],
                serializer.validated_data.get("extra_ball", 0), request=request,
            )
        except SubmissionError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        result.pop("details", None)  # to'g'ri javoblar javobda qaytarilmaydi
        return Response({**result, "grade": grade})


# ---------------------------------------------------------------------------
# Blok (DTM) testlari: /api/block-tests/
# ---------------------------------------------------------------------------

class BlockTestViewSet(viewsets.ModelViewSet):
    queryset = BlockTest.objects.select_related("creator")
    serializer_class = BlockTestSerializer

    @swagger_auto_schema(
        operation_summary="Yangi blok test yaratish",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'telegram_id': openapi.Schema(type=openapi.TYPE_INTEGER, description="Yaratuvchi Telegram ID"),
                'answer': openapi.Schema(type=openapi.TYPE_OBJECT, description="meta: fanlar, turlari va javoblar"),
            },
            required=['telegram_id', 'answer'],
        ),
        responses={201: BlockTestSerializer},
    )
    def create(self, request, *args, **kwargs):
        telegram_id, answer = request.data.get('telegram_id'), request.data.get('answer')
        if not telegram_id or not isinstance(answer, dict) or not answer:
            return Response({"error": "telegram_id va answer maydonlari talab qilinadi"},
                            status=status.HTTP_400_BAD_REQUEST)
        user = TelegramUser.objects.filter(telegram_id=telegram_id).first()
        if user is None:
            return Response({"error": "Foydalanuvchi topilmadi"}, status=status.HTTP_404_NOT_FOUND)
        test = BlockTest.objects.create(creator=user, meta=answer)
        notify_block_test_created(test)
        return Response(self.get_serializer(test).data, status=status.HTTP_201_CREATED)

    @swagger_auto_schema(
        operation_summary="Blok test javoblarini tekshirish",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'answer': openapi.Schema(type=openapi.TYPE_OBJECT, description="Javoblar (meta tuzilishida)"),
                'telegram_id': openapi.Schema(type=openapi.TYPE_INTEGER),
            },
            required=['answer', 'telegram_id'],
        ),
        responses={200: BlockTestResultResponseSerializer, 400: "Xatolik"},
    )
    @action(detail=True, methods=['post'])
    def check(self, request, pk=None):
        test = self.get_object()
        data = request.data
        params = data.get('params') if isinstance(data.get('params'), dict) else {}
        user_answers = data.get('answer') or data.get('user_answers') or params.get('answer')
        telegram_id = data.get('telegram_id') or params.get('telegram_id')
        if not telegram_id:
            return Response({"error": "telegram_id kiritish majburiy"}, status=status.HTTP_400_BAD_REQUEST)
        user = TelegramUser.objects.filter(telegram_id=telegram_id).first()
        if user is None:
            return Response({"error": "Foydalanuvchi topilmadi"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            *_, result = submit_block_test(test, user, user_answers, request=request)
        except SubmissionError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(BlockTestResultResponseSerializer(result).data)
