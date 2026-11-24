from rest_framework import serializers

from .models import BlockTest, BlockTestResult, BookTest, RequiredChannel, Subject, TelegramUser, Test


class TelegramUserSerializer(serializers.ModelSerializer):
    full_name = serializers.ReadOnlyField()
    balans_formatted = serializers.ReadOnlyField()
    
    class Meta:
        model = TelegramUser
        fields = [
            'id', 'telegram_id', 'username', 'surname', 'name', 'father_name',
            'phone', 'region', 'district', 'balance', 'balans_formatted',
            'full_name', 'is_active', 'is_banned', "is_admin", 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


class SubjectSerializer(serializers.ModelSerializer):
    tests_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Subject
        fields = [
            'id', 'name', 'description', 'is_active', 
            'tests_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']
    
    def get_tests_count(self, obj):
        return obj.tests.count()


class TestSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    creator_name = serializers.CharField(source='creator.full_name', read_only=True)
    
    class Meta:
        model = Test
        fields = [
            'id', 'subject', 'subject_name', 'creator', 'creator_name', "start_time",
            'title', 'questions_count', 'is_active', 'is_public',
            'channel_username', 'answers', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


# List serializers (simplified for list views)
class TelegramUserListSerializer(serializers.ModelSerializer):
    full_name = serializers.ReadOnlyField()
    
    class Meta:
        model = TelegramUser
        fields = [
            'id', 'telegram_id', 'username', 'full_name', 
            'phone', 'region', 'balance', 'is_active', 'is_banned', 'is_admin'
        ]


class SubjectListSerializer(serializers.ModelSerializer):
    tests_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Subject
        fields = ['id', 'name', 'is_active', 'tests_count', 'created_at']
    
    def get_tests_count(self, obj):
        return obj.tests.count()


class TestListSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    creator_name = serializers.CharField(source='creator.full_name', read_only=True)
    
    class Meta:
        model = Test
        fields = [
            'id', 'subject', 'subject_name', 'creator', 'creator_name', "start_time",
            'title', 'questions_count', 'is_active', 'is_public',
            'channel_username', 'answers', 'created_at', 'updated_at'
        ]

class RequiredChannelSerializer(serializers.ModelSerializer):
    class Meta:
        model = RequiredChannel
        fields = [
            'id', 'channel_id', 'channel_username', 'invite_link', 'is_active',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


class RequiredChannelListSerializer(serializers.ModelSerializer):
    class Meta:
        model = RequiredChannel
        fields = [
            'id', 'channel_id', 'channel_username', 'invite_link', 'is_active', 'created_at'
        ]



# ---------------------------------------------------------------------------
# Kitob testlari
# ---------------------------------------------------------------------------

class BookTestSerializer(serializers.ModelSerializer):
    creator_telegram_id = serializers.IntegerField(source="creator.telegram_id", read_only=True)

    class Meta:
        model = BookTest
        fields = [
            "id", "slug", "subject", "creator_telegram_id", "title", "questions_count",
            "answers", "scores", "book_test", "extra_ball",
        ]
        read_only_fields = ["slug", "questions_count"]


class BookTestCreateSerializer(serializers.ModelSerializer):
    telegram_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = BookTest
        fields = ["id", "telegram_id", "subject", "title", "answers", "scores", "book_test", "extra_ball"]

    def validate(self, attrs):
        answers = attrs.get("answers", {})
        scores = attrs.get("scores", [])
        if not isinstance(answers, dict) or not answers:
            raise serializers.ValidationError("answers dict formatida bo‘lishi va bo‘sh bo‘lmasligi kerak")
        if scores and len(scores) != len(answers):
            raise serializers.ValidationError("scores uzunligi answers bilan teng bo‘lishi kerak")
        return attrs

    def create(self, validated_data):
        telegram_id = validated_data.pop("telegram_id")
        creator = TelegramUser.objects.filter(telegram_id=telegram_id).first()
        if creator is None:
            raise serializers.ValidationError({"telegram_id": "Telegram user topilmadi"})
        return BookTest.objects.create(creator=creator, **validated_data)


class BookTestCheckAnswerSerializer(serializers.Serializer):
    telegram_id = serializers.IntegerField()
    answers = serializers.JSONField()
    extra_ball = serializers.FloatField(required=False, default=0, min_value=0)

    def validate_answers(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("answers dict formatida bo‘lishi kerak")
        return value


# ---------------------------------------------------------------------------
# Blok (DTM) testlari
# ---------------------------------------------------------------------------

class BlockTestSerializer(serializers.ModelSerializer):
    class Meta:
        model = BlockTest
        fields = ['id', 'creator', 'meta', 'is_active']


class BlockTestResultResponseSerializer(serializers.ModelSerializer):
    user_full_name = serializers.CharField(source='user.full_name', read_only=True)

    class Meta:
        model = BlockTestResult
        fields = ['id', 'user', 'user_full_name', 'test', 'total_score', 'correct_answers', 'detailed_results', 'created_at']
        read_only_fields = fields
