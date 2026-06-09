"""Bot actions — functions called by python-telegram-bot when events occur."""

# Actions
from .start import start_bot
from .profile_skill_creator import profile_analyzer
from .normal_message import message_bot
from .menu import ideas_submenu_show, ideas_submenu_route
from .compose_carousel import (
    compose_carousel_from_picked,
    generate_carousel_images,
    carousel_individual_route,
    carousel_publish_route,
)
from .compose_reel import compose_reel_from_picked
from .brainstorm_topics import (
    brainstorm_topics_from_vault,
    own_idea_start,
    own_idea_receive,
    brainstorm_own_process,
    WAITING_FOR_OWN_IDEA,
)
from .content_picker import (
    content_picker_entry,
    topic_picker_show,
    topic_picker_route,
    headline_picker_show,
    headline_picker_route,
    topic_picker_back_route,
    reel_format_picker_show,
    reel_format_picker_route,
)
from .viral_posts import (
    viral_submenu_show,
    viral_submenu_route,
    viral_receive_keyword,
    viral_remove_show,
    viral_remove_route,
    viral_back_submenu_route,
    viral_refresh_cache,
    viral_generate_report,
)
from .settings import (
    settings_submenu_show,
    settings_submenu_route,
    scheduler_submenu_show,
    scheduler_submenu_route,
    receive_background_photo,
    receive_logo_document,
    customize_submenu_show,
    customize_submenu_route,
)
from .admin import (
    status_command,
    broadcast_command,
    restart_command,
    testschedule_command,
    set_bot_start_time,
)
from .morning_ideas import (
    build_topics_message,
    morning_idea_route,
    morning_idea_format_route,
)

# States
from .onboarding import WAITING_FOR_HANDLE, CONFIRMING_HANDLE, WAITING_FOR_NICHE, CONFIRMING_NICHE, receive_handle, confirm_handle, receive_niche, confirm_niche, cancel