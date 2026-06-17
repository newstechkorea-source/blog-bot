import time
import streamlit as st
from google import genai
from PIL import Image

# ==========================================
# 🌟 설정 (비밀값은 코드가 아니라 secrets에서 읽어옵니다)
# ==========================================
# 실제 비밀번호와 API 키는 .streamlit/secrets.toml 파일에 넣습니다.
# (코드에는 비밀값을 절대 적지 않습니다. 공유/배포해도 안전하도록.)
def get_secret(name, default=""):
    try:
        return st.secrets[name]
    except Exception:
        return default

GEMINI_API_KEY = get_secret("GEMINI_API_KEY")
APP_PASSWORD = get_secret("APP_PASSWORD")

# 사용할 모델 (2026년 6월 기준 유효한 모델명)
#  - gemini-2.5-flash : 무료 티어 가능, 멀티모달, 속도/품질 균형 (추천)
#  - gemini-2.5-pro   : 더 높은 품질이지만 유료 전용
#  - gemini-3.5-flash : 최신 고성능 (무료 티어 제한적)
MODEL_NAME = "gemini-2.5-flash"

st.set_page_config(page_title="뷰로코리아 블로그 AI", page_icon="🏛️", layout="centered")


# ==========================================
# 🔒 비밀번호 게이트
# ==========================================
def check_password():
    """공용 비밀번호가 맞아야 통과. 비밀번호는 secrets에 보관."""
    if st.session_state.get("password_ok", False):
        return True

    def _verify():
        if APP_PASSWORD and st.session_state.get("password_input") == APP_PASSWORD:
            st.session_state["password_ok"] = True
            st.session_state.pop("password_input", None)  # 입력값은 메모리에서 제거
        else:
            st.session_state["password_ok"] = False

    st.title("🔒 뷰로코리아 블로그 AI")
    st.caption("사내 공용 도구입니다. 접속 비밀번호를 입력해 주세요.")

    if not APP_PASSWORD:
        st.error("관리자 설정 필요: secrets.toml 에 APP_PASSWORD 가 설정되지 않았습니다.")
        return False

    st.text_input("비밀번호", type="password", key="password_input", on_change=_verify)
    if "password_ok" in st.session_state and not st.session_state["password_ok"]:
        st.error("비밀번호가 올바르지 않습니다.")
    return False


if not check_password():
    st.stop()


# ==========================================
# 🌟 [도구 모음] 사진 용량을 줄여주는 함수
# ==========================================
def prepare_image_for_api(pil_image):
    max_size = 1024
    width, height = pil_image.size
    if width > max_size or height > max_size:
        ratio = min(max_size / width, max_size / height)
        new_size = (int(width * ratio), int(height * ratio))
        return pil_image.resize(new_size, Image.Resampling.LANCZOS)
    return pil_image


# 일시적 오류(503 과부하, 429 한도 등)면 잠시 쉬었다가 자동으로 다시 시도
def generate_with_retry(client, model, contents, max_retries=4):
    delay = 2  # 초 (2 → 4 → 8 식으로 늘어남)
    last_err = None
    for attempt in range(max_retries):
        try:
            return client.models.generate_content(model=model, contents=contents)
        except Exception as e:
            last_err = e
            msg = str(e)
            transient = any(
                k in msg
                for k in ["503", "UNAVAILABLE", "overloaded", "429", "RESOURCE_EXHAUSTED", "500", "INTERNAL"]
            )
            if transient and attempt < max_retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise last_err


# ==========================================
# 🌟 [메인 화면 로직]
# ==========================================
st.title("🏛️ 뷰로코리아 블로그 에이전트")
st.caption("주제와 사진을 넣으면, 뷰로코리아 톤에 맞춘 전문가형 네이버 포스팅을 작성해 줍니다.")
st.markdown("---")

st.subheader("📝 어떤 포스팅을 할까요?")

user_topic = st.text_area(
    "글의 핵심 주제나 키워드를 짧게 적어주세요.",
    placeholder="예: 베리알록 헤링본 바닥재 시공 / 아글로텍 테라조 슬랩 / 욕실 수전·조명 마감 제안",
    height=100,
)

uploaded_files = st.file_uploader(
    "이미지 추가 (최대 10장)",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True,
)

if uploaded_files:
    if len(uploaded_files) > 10:
        st.warning("사진은 최대 10장까지만 분석됩니다.")
        uploaded_files = uploaded_files[:10]

    # 한 줄에 최대 5장씩 미리보기 (파일명도 함께 표시)
    for row_start in range(0, len(uploaded_files), 5):
        row_files = uploaded_files[row_start:row_start + 5]
        cols = st.columns(len(row_files))
        for col, file in zip(cols, row_files):
            with col:
                file.seek(0)  # 미리보기와 API 전송에서 두 번 읽으므로 위치 초기화
                st.image(Image.open(file), caption=file.name, use_container_width=True)

st.markdown("---")

if st.button("✨ 네이버 최적화 블로그 글 생성", type="primary", use_container_width=True):
    if not GEMINI_API_KEY:
        st.error("관리자 설정 필요: secrets.toml 에 GEMINI_API_KEY 가 설정되지 않았습니다.")
    elif not user_topic:
        st.warning("주제나 키워드를 입력해 주세요.")
    else:
        with st.spinner("뷰로코리아 톤으로 전문가형 포스팅을 작성 중입니다... (최대 1~2분 소요)"):
            try:
                client = genai.Client(api_key=GEMINI_API_KEY)

                prompt = (
                    "당신은 프리미엄 인테리어 건축 소재 기업 '뷰로코리아(VIEURO KOREA)'의 콘텐츠를 책임지는 전문 에디터이자 공간 디렉터입니다.\n"
                    "뷰로코리아는 '프리미엄 소재로 공간의 본질을 완성한다'를 지향하며, 유럽·이탈리아 기반의 프리미엄 바닥재(BerryAlloc), 베네치안 테라조(Agglotech), "
                    "세라믹 타일·대형 슬랩(Anatolia·Dewata), 하이엔드 스마트 라이팅(L-light), 이탈리아 수전(I Crolla)을 다룹니다.\n"
                    "제공된 사진들과 아래 핵심 키워드를 바탕으로, 소재의 물성과 디자인 가치를 깊이 이해한 '전문가'의 시점에서 신뢰감 있는 포스팅을 작성해 주세요.\n\n"
                    "[톤앤매너 — 매우 중요]\n"
                    "- 맛집·일상 후기 블로거 같은 가벼운 호들갑 톤은 절대 금지합니다(과도한 감탄사, 'ㅎㅎ', 이모지 남발 금지).\n"
                    "- 정제되고 전문적이되 읽기 편한 경어체(~합니다, ~됩니다)를 사용하고, 소재·디자인·시공에 대한 구체적 지식과 안목이 드러나도록 작성하세요.\n"
                    "- 브랜드의 격(프리미엄, 타임리스)에 어울리는 차분하고 신뢰감 있는 문체를 유지하세요. 이모지는 쓰지 않거나 꼭 필요할 때 최소한으로만 절제해 사용합니다.\n\n"
                    "[전문성 가이드]\n"
                    "1. 소재 관점의 깊이: 사진 속 소재의 질감·색감·마감·패턴과 내구성·관리성 같은 물성, 그리고 공간에서의 활용을 전문가 시각으로 구체적으로 설명하세요.\n"
                    "2. 공간·디자인 맥락: 해당 소재가 어떤 공간(주거/상업/욕실/주방 등)과 무드에 어울리는지, 조명·가구·다른 마감재와의 조화를 제안하세요.\n"
                    "3. 신뢰 구축: 막연한 미사여구가 아니라 근거 있는 설명으로 전문성과 경험을 전달해, 독자가 '믿고 맡길 수 있는 곳'이라는 인상을 받도록 하세요.\n"
                    "4. 네이버 검색 최적화: 핵심 키워드를 자연스럽게 녹이고, 소제목(##)으로 구조를 잡으며, 모바일에서 읽기 편하도록 문단을 2~3줄 단위로 정리하세요.\n\n"
                    "[사진 활용 규칙 — 반드시 지킬 것]\n"
                    "- 업로드된 사진은 '[사진 1]', '[사진 2]' … 순서로 번호와 파일명이 함께 제공됩니다.\n"
                    "- 본문에서 각 사진을 해당 번호와 파일명을 그대로 표기하며 소개하고, 그 사진에 맞는 설명·멘트를 이어서 작성하세요.\n"
                    "  (예: '[사진 1] (파일명: living_floor.jpg) — 거실 바닥에 시공된 …')\n"
                    "- 사진에 실제로 보이는 요소만 근거로 묘사하고, 보이지 않는 내용을 지어내지 마세요.\n\n"
                    f"작성해야 할 핵심 주제 및 키워드: {user_topic}"
                )

                contents = [prompt]
                if uploaded_files:
                    for idx, file in enumerate(uploaded_files, start=1):
                        file.seek(0)
                        img = Image.open(file)
                        # 각 사진 앞에 번호와 파일명을 텍스트로 붙여 모델이 매칭하도록 함
                        contents.append(f"[사진 {idx}] 파일명: {file.name}")
                        contents.append(prepare_image_for_api(img))

                response = generate_with_retry(client, MODEL_NAME, contents)

                st.success("✨ 포스팅 초안이 완성되었습니다!")
                st.markdown("### 📋 생성된 블로그 본문")
                st.text_area(
                    "결과물 (복사해서 네이버 블로그에 붙여넣으세요)",
                    value=response.text,
                    height=500,
                )

            except Exception as e:
                msg = str(e)
                if any(k in msg for k in ["503", "UNAVAILABLE", "overloaded", "429", "RESOURCE_EXHAUSTED"]):
                    st.error("지금 AI 서버 요청이 몰려 일시적으로 응답이 어렵습니다. 잠시 후 생성 버튼을 다시 눌러 주세요. (구글 측 일시 과부하)")
                else:
                    st.error(f"오류가 발생했습니다: {e}")
