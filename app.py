import io
import time
import zipfile
import datetime
import streamlit as st
from google import genai
from PIL import Image

# ==========================================
# 🌟 설정 (비밀값은 코드가 아니라 secrets에서 읽어옵니다)
# ==========================================
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
            st.session_state.pop("password_input", None)
        else:
            st.session_state["password_ok"] = False

    st.title("🔒 뷰로코리아 블로그 AI")
    st.caption("사내 공용 도구입니다. 접속 비밀번호를 입력해 주세요.")

    if not APP_PASSWORD:
        st.error("관리자 설정 필요: Secrets 에 APP_PASSWORD 가 설정되지 않았습니다.")
        return False

    st.text_input("비밀번호", type="password", key="password_input", on_change=_verify)
    if "password_ok" in st.session_state and not st.session_state["password_ok"]:
        st.error("비밀번호가 올바르지 않습니다.")
    return False


if not check_password():
    st.stop()


# ==========================================
# 🌟 도구 함수
# ==========================================
def prepare_image_for_api(pil_image):
    max_size = 768  # 분석용 해상도 (장수를 늘렸으므로 용량·토큰 절약 위해 축소)
    width, height = pil_image.size
    if width > max_size or height > max_size:
        ratio = min(max_size / width, max_size / height)
        new_size = (int(width * ratio), int(height * ratio))
        return pil_image.resize(new_size, Image.Resampling.LANCZOS)
    return pil_image


def generate_with_retry(client, model, contents, max_retries=4):
    """일시적 오류(503 과부하, 429 한도 등)면 잠시 쉬었다가 자동 재시도."""
    delay = 2
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


def build_export_zip(text, images):
    """생성된 글(.txt)과 사진들을 ZIP 하나로 묶어 bytes 반환."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("블로그_본문.txt", text.encode("utf-8"))
        for idx, (name, data) in enumerate(images, start=1):
            zf.writestr(f"사진_{idx:02d}_{name}", data)
    return buffer.getvalue()


# ==========================================
# 🌟 메인 화면
# ==========================================
st.title("🏛️ 뷰로코리아 블로그 에이전트")
st.caption("주제와 사진을 넣으면, 네이버 검색에 최적화된 뷰로코리아 전문가형 포스팅을 작성해 줍니다.")
st.markdown("---")

st.subheader("📝 검색 노출 키워드 설정")

col1, col2 = st.columns(2)
with col1:
    main_keyword = st.text_input("🔑 메인 키워드 (필수)", placeholder="예: 성수동 세라믹 타일")
with col2:
    sub_keyword = st.text_input("🏷️ 서브 키워드 (선택)", placeholder="예: 프리미엄 인테리어, 아나톨리아")

user_topic = st.text_area(
    "📝 이번 글에서 특별히 강조할 내용 (선택)",
    placeholder="예: 이번 현장은 넓은 공간감을 주기 위해 밝은 톤의 베리알록 바닥재를 사용했습니다.",
    height=80,
)

uploaded_files = st.file_uploader(
    "이미지 추가 (최대 30장)",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True,
)

if uploaded_files:
    if len(uploaded_files) > 30:
        st.warning("사진은 최대 30장까지만 분석됩니다.")
        uploaded_files = uploaded_files[:30]

    for row_start in range(0, len(uploaded_files), 5):
        row_files = uploaded_files[row_start:row_start + 5]
        cols = st.columns(len(row_files))
        for col, file in zip(cols, row_files):
            with col:
                file.seek(0)
                st.image(Image.open(file), caption=file.name, use_container_width=True)

st.markdown("---")

if st.button("✨ 네이버 최적화 블로그 글 생성", type="primary", use_container_width=True):
    if not GEMINI_API_KEY:
        st.error("관리자 설정 필요: Secrets 에 GEMINI_API_KEY 가 설정되지 않았습니다.")
    elif not main_keyword:
        st.warning("메인 키워드를 입력해 주세요. (필수)")
    else:
        with st.spinner("뷰로코리아 톤으로 전문가형 포스팅을 작성 중입니다... (최대 1~2분 소요)"):
            try:
                client = genai.Client(api_key=GEMINI_API_KEY)

                prompt = (
                    "당신은 프리미엄 인테리어 건축 소재 기업 '뷰로코리아(VIEURO KOREA)'의 콘텐츠를 책임지는 전문 에디터이자 공간 디렉터입니다.\n"
                    "뷰로코리아는 '프리미엄 소재로 공간의 본질을 완성한다'를 지향하며, 유럽·이탈리아 기반의 프리미엄 바닥재(BerryAlloc), 베네치안 테라조(Agglotech), "
                    "세라믹 타일·대형 슬랩(Anatolia·Dewata), 하이엔드 스마트 라이팅(L-light), 이탈리아 수전(I Crolla)을 다룹니다.\n"
                    "제공된 사진들과 아래 [타겟 키워드]를 바탕으로, 네이버 검색 노출(SEO)에 최적화된 신뢰감 있는 전문가형 블로그 포스팅을 작성해 주세요.\n\n"
                    "[타겟 키워드]\n"
                    f"- 메인 키워드: {main_keyword}\n"
                    f"- 서브 키워드: {sub_keyword}\n"
                    f"- 추가 강조 내용: {user_topic}\n\n"
                    "[톤앤매너 — 매우 중요]\n"
                    "- 맛집·일상 후기 블로거 같은 가벼운 호들갑 톤은 절대 금지합니다(과도한 감탄사, 'ㅎㅎ', 이모지 남발 금지).\n"
                    "- 정제되고 전문적이되 읽기 편한 경어체(~합니다, ~됩니다)를 사용하고, 소재·디자인·시공에 대한 구체적 지식과 안목이 드러나도록 작성하세요.\n"
                    "- 브랜드의 격(프리미엄, 타임리스)에 어울리는 차분하고 신뢰감 있는 문체를 유지하세요. 이모지는 쓰지 않거나 꼭 필요할 때 최소한으로만 절제해 사용합니다.\n\n"
                    "[전문성 가이드]\n"
                    "1. 소재 관점의 깊이: 사진 속 소재의 질감·색감·마감·패턴과 내구성·관리성 같은 물성, 그리고 공간에서의 활용을 전문가 시각으로 구체적으로 설명하세요.\n"
                    "2. 공간·디자인 맥락: 해당 소재가 어떤 공간(주거/상업/욕실/주방 등)과 무드에 어울리는지, 조명·가구·다른 마감재와의 조화를 제안하세요.\n"
                    "3. 신뢰 구축: 막연한 미사여구가 아니라 근거 있는 설명으로 전문성과 경험을 전달해, 독자가 '믿고 맡길 수 있는 곳'이라는 인상을 받도록 하세요.\n\n"
                    "[글 분량 — 반드시 지킬 것]\n"
                    "- 본문 설명 글을 공백 포함 약 1,800자 내외(±200자, 즉 1,600~2,000자)로 일관되게 작성하세요.\n"
                    "- 이때 [사진 캡션]과 맨 끝의 #해시태그는 글자 수 계산에서 제외합니다. 순수하게 본문 설명 글만 1,800자 내외로 맞추세요.\n"
                    "- 사진 수가 많아도 각 사진 설명을 간결히 조절해 이 분량을 유지하고, 분량을 채우려고 의미 없는 미사여구를 늘리지 마세요.\n\n"
                    "[네이버 블로그 SEO 규칙 — 반드시 지킬 것]\n"
                    "1. 제목 최적화: 글의 제목은 최상단에 '# 제목: [여기에 제목 작성]' 형태로 출력하되, 25자를 넘지 않게 작성하고 [메인 키워드]를 반드시 문장에 배치하세요.\n"
                    "2. 서론 키워드 배치: 글의 첫 번째 문단 안에 [메인 키워드]와 [서브 키워드]가 자연스럽게 포함되도록 작성하여 검색 로봇이 주제를 빠르게 파악하게 하세요.\n"
                    "3. 모바일 가독성: 스마트폰으로 읽기 편하도록 반드시 줄 바꿈을 하고, 명확한 소제목(##)으로 단락을 구분하세요.\n"
                    "4. 사진 캡션(설명) 생성: 본문에 사진을 삽입할 때, 사진 바로 아래에 [사진 캡션: 메인/서브 키워드를 포함한 짧은 한 줄 설명]을 반드시 작성해 주세요. 이는 네이버 이미지 검색 노출에 매우 중요합니다.\n"
                    "5. 해시태그: 글의 맨 마지막에는 네이버 블로그에 바로 복사해 넣을 수 있도록 [메인 키워드]와 [서브 키워드]를 포함한 #해시태그 7~10개를 추천해 주세요.\n\n"
                    "[사진 활용 규칙]\n"
                    "- 업로드된 사진은 '[사진 1]', '[사진 2]' … 순서로 번호와 파일명이 함께 제공됩니다.\n"
                    "- 본문에서 각 사진을 소개할 때 번호와 파일명을 명시하고, 그 아래에 캡션을 달고 이어서 본문을 작성하세요.\n"
                    "  (예: '[사진 1] (파일명: living_floor.jpg)\n[사진 캡션: 성수동 세라믹 타일로 마감한 거실 인테리어]\n거실 바닥에 시공된 프리미엄 타일은...')\n"
                    "- 사진에 실제로 보이는 요소만 묘사하고, 보이지 않는 내용은 지어내지 마세요."
                )

                contents = [prompt]
                export_images = []
                if uploaded_files:
                    for idx, file in enumerate(uploaded_files, start=1):
                        file.seek(0)
                        raw = file.read()              # 내보내기용 원본 보관
                        export_images.append((file.name, raw))
                        img = Image.open(io.BytesIO(raw))
                        contents.append(f"[사진 {idx}] 파일명: {file.name}")
                        contents.append(prepare_image_for_api(img))

                response = generate_with_retry(client, MODEL_NAME, contents)

                # 결과를 세션에 저장 (다운로드 버튼을 눌러도 사라지지 않도록)
                st.session_state["result_text"] = response.text
                st.session_state["result_images"] = export_images

                # 이번 세션 작업 이력에 추가 (텍스트만 보관 / 새로고침 시 초기화)
                st.session_state.setdefault("history", [])
                st.session_state["hist_counter"] = st.session_state.get("hist_counter", 0) + 1
                st.session_state["history"].insert(0, {
                    "id": st.session_state["hist_counter"],
                    "time": datetime.datetime.now().strftime("%m/%d %H:%M"),
                    "main": main_keyword,
                    "sub": sub_keyword,
                    "text": response.text,
                })
                st.session_state["history"] = st.session_state["history"][:30]  # 너무 쌓이지 않게 30개 제한

            except Exception as e:
                msg = str(e)
                if any(k in msg for k in ["503", "UNAVAILABLE", "overloaded", "429", "RESOURCE_EXHAUSTED"]):
                    st.error("지금 AI 서버 요청이 몰려 일시적으로 응답이 어렵습니다. 잠시 후 생성 버튼을 다시 눌러 주세요. (구글 측 일시 과부하)")
                else:
                    st.error(f"오류가 발생했습니다: {e}")


# ==========================================
# 📋 결과 표시 + 내보내기 (세션에 저장돼 있어 다운로드를 눌러도 유지됨)
# ==========================================
if st.session_state.get("result_text"):
    st.success("✨ 포스팅 초안이 완성되었습니다!")
    st.markdown("### 📋 생성된 블로그 본문")
    st.text_area(
        "결과물 (복사해서 네이버 블로그에 붙여넣으세요)",
        value=st.session_state["result_text"],
        height=500,
    )

    zip_bytes = build_export_zip(
        st.session_state["result_text"],
        st.session_state.get("result_images", []),
    )
    st.download_button(
        "📦 글 + 사진 한 번에 내보내기 (ZIP)",
        data=zip_bytes,
        file_name="뷰로코리아_블로그_포스팅.zip",
        mime="application/zip",
        use_container_width=True,
    )
    st.caption("ZIP 안에 '블로그_본문.txt'와 번호 매겨진 사진들이 들어 있어, 본문의 [사진 N] 순서대로 맞춰 올리시면 됩니다.")


# ==========================================
# 📜 이번 세션 작업 이력 (사이드바 / 텍스트만, 새로고침 시 초기화)
# ==========================================
with st.sidebar:
    st.header("📜 이번 세션 작업 이력")
    history = st.session_state.get("history", [])
    if not history:
        st.caption("아직 생성한 글이 없습니다. 글을 만들면 여기에 쌓입니다.")
    else:
        st.caption("⚠️ 새로고침하거나 다시 접속하면 초기화됩니다.")
        for item in history:
            label = f"{item['time']} · {item['main'] or '(키워드 없음)'}"
            with st.expander(label):
                st.text_area(
                    "본문",
                    value=item["text"],
                    height=200,
                    key=f"hist_{item['id']}",
                )
                fname = "블로그_" + item["time"].replace("/", "").replace(":", "").replace(" ", "_") + ".txt"
                st.download_button(
                    "📄 이 글 .txt로 받기",
                    data=item["text"].encode("utf-8"),
                    file_name=fname,
                    mime="text/plain",
                    key=f"hist_dl_{item['id']}",
                    use_container_width=True,
                )
