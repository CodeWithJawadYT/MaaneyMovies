"""
============================================================
 MAANEYMOVIES — single-file FastAPI backend (index.py)
 ------------------------------------------------------------
 Everything in one file: movie catalogue (33 public-domain FULL
 feature films streamed from the Internet Archive), JWT email/
 password auth, and a per-user watchlist (MongoDB).

 HOW TO RUN LOCALLY
   1) Install deps:
        pip install "fastapi[all]" uvicorn motor pyjwt bcrypt pydantic[email] python-dotenv
   2) Make sure MongoDB is running locally (mongodb://localhost:27017)
      or set MONGO_URL / DB_NAME environment variables.
   3) Start the server:
        python index.py
      (or: uvicorn index:app --reload --port 8001)
   4) Open http://localhost:8001/api/  — and point your frontend at it.

 Default admin login:  admin@maaneymovies.com  /  Admin@123
============================================================
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import jwt
import bcrypt
import uvicorn
from bson import ObjectId
from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Query
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr, Field

# ---------------------------------------------------------------------------
# Config (override any of these with environment variables)
# ---------------------------------------------------------------------------
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "maaneymovies")
JWT_SECRET = os.environ.get("JWT_SECRET", "change-this-secret")
JWT_ALGO = "HS256"
JWT_EXP_DAYS = 7
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@maaneymovies.com").lower()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@123")
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*").split(",")

IMG_BASE = "https://image.tmdb.org/t/p/"   # legacy TMDB poster base (unused by the seed)

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("maaneymovies")

# ---------------------------------------------------------------------------
# Movie catalogue — 33 public-domain FULL feature films (archive.org .mp4)
# ---------------------------------------------------------------------------
EN, HI = "en", "hi"
ARCH = "https://archive.org/download/"
IMG = "https://archive.org/services/img/"


def _m(id, title, language, genres, rating, year, runtime, popularity, audio, ident, mp4, overview):
    return dict(
        id=id, title=title, language=language, genres=genres, rating=rating,
        year=year, runtime=runtime, popularity=popularity, audio=audio,
        hindi_dubbed=False, trailer=None,
        poster=f"{IMG}{ident}", backdrop=None,
        video_url=f"{ARCH}{ident}/{mp4}", overview=overview,
    )


MOVIES_SEED = [
    # ---------------- Hollywood / English classics ----------------
    _m(1001, "Metropolis", EN, ["Sci-Fi", "Drama"], 8.3, "1927", 153, 100, ["Silent"],
       "Metropolis1927EnglishVersion", "Metropolis_1927_English_Version.mp4",
       "In a futuristic city sharply divided between the working class and the city planners, the son of the city's mastermind falls in love with a working-class prophet who predicts the coming of a savior."),
    _m(1002, "Night of the Living Dead", EN, ["Horror", "Thriller"], 7.8, "1968", 96, 99, ["English"],
       "PhantasmagoriaTheater-NightOfTheLivingDead1968321", "PhantasmagoriaTheater-NightOfTheLivingDead1968321_512kb.mp4",
       "A ragtag group of strangers barricade themselves inside an old farmhouse to survive the night as the recently dead rise and feed on the living."),
    _m(1003, "The General", EN, ["Comedy", "Action", "Adventure"], 8.1, "1926", 67, 95, ["Silent"],
       "TheGeneral1926", "The_General_1926_720p.mp4",
       "When Union spies steal his beloved locomotive — with his girl aboard — a Confederate railroad engineer single-handedly chases them through enemy lines in Buster Keaton's masterpiece."),
    _m(1004, "Charade", EN, ["Thriller", "Comedy", "Romance"], 7.9, "1963", 113, 94, ["English"],
       "charade-stanley-donen-1963-cary-grant-audrey-hepburn-comedie-policiere",
       "Charade%20Stanley%20Donen%201963%20Cary%20Grant%20Audrey%20Hepburn%20Com%C3%A9die%20polici%C3%A8re.mp4",
       "A woman is pursued by several men who want a fortune her murdered husband had stolen. Whom can she trust? Cary Grant and Audrey Hepburn star in this elegant romantic thriller."),
    _m(1005, "Nosferatu", EN, ["Horror"], 7.9, "1922", 94, 92, ["Silent"],
       "Nosferatu1922", "Nosferatu.mp4",
       "Vampire Count Orlok expresses interest in a new residence and a real-estate agent's wife in this haunting, unauthorized silent adaptation of Bram Stoker's Dracula."),
    _m(1006, "His Girl Friday", EN, ["Comedy", "Romance"], 7.8, "1940", 92, 90, ["English"],
       "his_girl_friday", "his_girl_friday.mp4",
       "A newspaper editor uses every trick in the book to keep his ace reporter ex-wife from remarrying — a lightning-fast screwball comedy classic."),
    _m(1007, "The Cabinet of Dr. Caligari", EN, ["Horror", "Thriller"], 8.0, "1920", 67, 84, ["Silent"],
       "thecabinetofdrcaligari", "KabinettDesDoktorCaligariDas_512kb.mp4",
       "A hypnotist uses a sleepwalker to commit murders in this landmark of German Expressionist cinema, told with dizzying painted sets and a famous twist."),
    _m(1008, "Detour", EN, ["Crime", "Thriller", "Drama"], 7.2, "1945", 67, 83, ["English"],
       "detour_1945", "detour_4k.ia.mp4",
       "A down-on-his-luck pianist hitchhiking to Hollywood is dragged into a spiral of bad luck, blackmail and death in this quintessential film noir."),
    _m(1009, "The Stranger", EN, ["Thriller", "Crime", "Drama"], 7.3, "1946", 95, 82, ["English"],
       "TheStranger_0", "The_Stranger.mp4",
       "An investigator hunts a fugitive Nazi war criminal who has assumed a new identity in a quiet Connecticut town. Directed by and starring Orson Welles."),
    _m(1010, "The 39 Steps", EN, ["Thriller", "Crime"], 7.6, "1935", 86, 80, ["English"],
       "youtube-RmSdum4BMqI", "RmSdum4BMqI.mp4",
       "An ordinary man is plunged into a spy conspiracy and goes on the run, handcuffed to a stranger, in Alfred Hitchcock's breathless early thriller."),
    _m(1011, "Carnival of Souls", EN, ["Horror"], 7.0, "1962", 78, 78, ["English"],
       "CarnivalOfSouls1962", "Carnival_of_Souls_512kb.mp4",
       "After surviving a car crash, a young organist is drawn to an abandoned carnival pavilion and haunted by a ghostly pale-faced man in this eerie cult classic."),
    _m(1012, "House on Haunted Hill", EN, ["Horror", "Thriller"], 6.8, "1959", 75, 76, ["English"],
       "house_on_haunted_hill", "house_on_haunted_hill.mp4",
       "An eccentric millionaire offers five guests $10,000 each if they can survive a night locked inside a haunted mansion. Starring Vincent Price."),
    _m(1013, "The Last Man on Earth", EN, ["Horror", "Sci-Fi"], 6.8, "1964", 86, 74, ["English"],
       "TheLastManOnEarthHD", "The%20Last%20Man%20on%20Earth%20HD.mp4",
       "The lone survivor of a plague that turned humanity into vampires hunts the infected by day and barricades himself by night. Vincent Price stars."),
    _m(1014, "A Star Is Born", EN, ["Drama", "Romance"], 7.4, "1937", 111, 72, ["English"],
       "AStarIsBorn1937FullHDMovie", "AStarIsBorn%281937%29FullHDMovie.mp4",
       "A young actress rises to Hollywood stardom while the fading star who discovered and married her spirals into decline — the original 1937 classic."),
    _m(1015, "Suddenly", EN, ["Thriller", "Crime"], 6.7, "1954", 75, 70, ["English"],
       "suddenly", "suddenly.mp4",
       "Assassins seize a family's home overlooking a train station, plotting to kill the President as he passes through a small town. Frank Sinatra stars against type."),
    _m(1016, "Nothing Sacred", EN, ["Comedy", "Romance"], 7.0, "1937", 77, 68, ["English"],
       "nothingsacred1937", "Nothing%20Sacred%20%281937%29.mp4",
       "A small-town woman wrongly believed to be dying of radium poisoning becomes a media sensation in New York in this sharp Technicolor screwball satire."),
    _m(1017, "McLintock!", EN, ["Comedy", "Adventure", "Western"], 7.0, "1963", 127, 66, ["English"],
       "mclintok_widescreen", "McLintock.mp4",
       "A wealthy cattle baron's estranged wife returns to town demanding a divorce, sparking a boisterous battle of the sexes. John Wayne and Maureen O'Hara star."),
    _m(1018, "My Favorite Brunette", EN, ["Comedy", "Crime"], 7.0, "1947", 87, 64, ["English"],
       "my_favorite_brunette", "my_favorite_brunette.mp4",
       "A mild-mannered baby photographer is mistaken for a private eye and tangled up with a glamorous baroness and a gang of crooks. Bob Hope comedy."),
    _m(1019, "The Little Shop of Horrors", EN, ["Comedy", "Horror"], 6.2, "1960", 72, 62, ["English"],
       "TheLittleShopOfHorrors1960_765", "TheLittleShopOfHorrors1960.mp4",
       "A clumsy florist's assistant raises a man-eating plant that demands to be fed in Roger Corman's beloved low-budget black comedy."),
    _m(1020, "Plan 9 from Outer Space", EN, ["Sci-Fi", "Horror"], 4.0, "1959", 79, 60, ["English"],
       "774-plan-9-from-outer-space", "774-Plan9FromOuterSpace.mp4",
       "Aliens resurrect the dead to stop humanity from creating a doomsday weapon — Ed Wood's gloriously inept film, famous as 'the worst movie ever made.'"),
    _m(1021, "The Phantom of the Opera", EN, ["Horror", "Drama"], 7.5, "1925", 93, 58, ["Silent"],
       "ThePhantomoftheOpera", "Phantom_of_the_Opera_512kb.mp4",
       "A disfigured musical genius haunting the Paris Opera House becomes obsessed with a beautiful young soprano. Lon Chaney's iconic silent horror."),
    _m(1022, "The Lost World", EN, ["Sci-Fi", "Adventure"], 7.0, "1925", 64, 56, ["Silent"],
       "lost_world", "lost_world.mp4",
       "An expedition to a remote plateau discovers living dinosaurs in this pioneering silent adventure featuring groundbreaking stop-motion effects."),
    _m(1023, "20,000 Leagues Under the Sea", EN, ["Sci-Fi", "Adventure"], 6.1, "1916", 105, 54, ["Silent"],
       "20000LeaguesUndertheSea", "20000_Leagues_Under_the_Sea_512kb.mp4",
       "The mysterious Captain Nemo prowls the oceans in his submarine Nautilus in this early adaptation of Jules Verne, the first film shot underwater."),
    _m(1024, "The Brain That Wouldn't Die", EN, ["Horror", "Sci-Fi"], 4.4, "1962", 82, 52, ["English"],
       "brain_that_wouldnt_die", "brain_that_wouldnt_die.mp4",
       "A surgeon keeps his fiancée's severed head alive after a car crash while searching for a new body — a notorious B-movie cult favorite."),
    _m(1025, "Gulliver's Travels", EN, ["Animation", "Family", "Adventure"], 6.5, "1939", 76, 50, ["English"],
       "gullivers_travels1939", "gullivers_travels1939.mp4",
       "Shipwrecked Gulliver washes ashore in the tiny kingdom of Lilliput and must stop two warring lands from going to war over a song. Lavish Fleischer animation."),
    _m(1026, "Jungle Book", EN, ["Adventure", "Family", "Fantasy"], 6.8, "1942", 108, 48, ["English"],
       "JungleBook", "Jungle_Book.mp4",
       "Raised by wolves, the boy Mowgli grows up among the animals of the Indian jungle and confronts the world of men. Technicolor adaptation of Kipling, starring Sabu."),
    _m(1027, "Scrooge", EN, ["Drama", "Fantasy"], 6.7, "1935", 78, 46, ["English"],
       "Scrooge1935_201310", "Scrooge_1935.mp4",
       "On Christmas Eve, the miserly Ebenezer Scrooge is visited by three spirits who show him the error of his ways in this early sound adaptation of Dickens."),
    _m(1028, "Santa Claus Conquers the Martians", EN, ["Sci-Fi", "Comedy", "Family"], 3.8, "1964", 81, 44, ["English"],
       "SantaClausConquerstheMartians1964", "SantaClausConquerstheMartians1964.mp4",
       "Martians kidnap Santa Claus to bring Christmas cheer to their joyless children — a delightfully cheesy cult holiday romp."),

    # ---------------- Indian / Hindi classics ----------------
    _m(2001, "Achhut Kanya", HI, ["Drama", "Romance"], 6.9, "1936", 74, 96, ["Hindi"],
       "achhut-kanya-1936-sd-640-480", "Achhut%20Kanya%20%281936%29%20SD%20640%20480.ia.mp4",
       "A landmark of early Hindi cinema: a doomed love story between a Brahmin boy and an untouchable girl that boldly challenged caste prejudice. Stars Ashok Kumar and Devika Rani."),
    _m(2002, "Dr. Kotnis Ki Amar Kahani", HI, ["Drama", "History"], 7.0, "1946", 120, 90, ["Hindi"],
       "senhor-doutor", "senhor%20doutor.ia.mp4",
       "The true story of Dr. Dwarkanath Kotnis, an Indian physician who travelled to China during the war to treat wounded soldiers. A V. Shantaram classic (with English subtitles)."),
    _m(2003, "Sant Tukaram", HI, ["Drama", "Musical"], 7.2, "1936", 131, 84, ["Marathi"],
       "sant-tukaram-1936_202604", "Sant_Tukaram_%281936%29.mp4",
       "The devotional life of the 17th-century poet-saint Tukaram — the first Indian film to win an award at the Venice Film Festival."),
    _m(2004, "Raja Harishchandra", HI, ["Drama", "History"], 7.0, "1913", 40, 78, ["Silent"],
       "RajaHarishchandra1913", "raja-harishchandra-1913.mp4",
       "India's very first full-length feature film: the legend of the truthful King Harishchandra, who sacrifices his kingdom, family and freedom to keep his word."),
    _m(2005, "Mahatma Gandhi: Pilgrim of Peace", EN, ["Documentary", "History", "Drama"], 7.0, "2005", 90, 64, ["English"],
       "MahatmaGandhi-PilgrimOfPeace", "Gandhi-PilgrimOfPeace_512kb.mp4",
       "A documentary portrait of Mohandas Karamchand Gandhi — his philosophy of non-violence and the freedom struggle that inspired the world."),
]

HOME_ROWS = [
    {"key": "trending", "name": "Trending Now"},
    {"key": "hindi", "name": "Indian Classics"},
    {"key": "hollywood", "name": "Hollywood Classics"},
    {"key": "horror", "name": "Horror"},
    {"key": "comedy", "name": "Comedy"},
    {"key": "scifi", "name": "Sci-Fi"},
    {"key": "thriller", "name": "Thriller & Noir"},
    {"key": "drama", "name": "Drama"},
]
GENRE_KEYS = {
    "action": "Action", "comedy": "Comedy", "scifi": "Sci-Fi", "horror": "Horror",
    "thriller": "Thriller", "romance": "Romance", "drama": "Drama", "animation": "Animation",
}

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="Maaneymovies API")
api_router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Movie helpers
# ---------------------------------------------------------------------------
def public_movie(m: dict) -> dict:
    poster = m.get("poster")
    poster_url = poster if (poster and poster.startswith("http")) else ((IMG_BASE + "w500" + poster) if poster else None)
    backdrop = m.get("backdrop")
    backdrop_url = backdrop if (backdrop and backdrop.startswith("http")) else ((IMG_BASE + "original" + backdrop) if backdrop else None)
    return {
        "id": m["id"],
        "title": m["title"],
        "year": m.get("year"),
        "release_date": str(m.get("year", "")) + "-01-01" if m.get("year") else None,
        "language": m.get("language"),
        "language_label": "Hindi" if m.get("language") == "hi" else "English",
        "genres": m.get("genres", []),
        "vote_average": m.get("rating"),
        "overview": m.get("overview"),
        "poster_path": m.get("poster"),
        "poster_url": poster_url,
        "backdrop_path": m.get("backdrop"),
        "backdrop_url": backdrop_url,
        "trailer_key": m.get("trailer"),
        "video_url": m.get("video_url"),
        "audio": m.get("audio", ["English"]),
        "hindi_dubbed": m.get("hindi_dubbed", False),
        "popularity": m.get("popularity", 0),
    }


async def query_movies(language=None, genre=None, dubbed=None, query=None, sort="popularity"):
    q: dict = {}
    if language in ("hi", "en"):
        q["language"] = language
    if genre:
        q["genres"] = genre
    if dubbed:
        q["hindi_dubbed"] = True
    if query:
        q["title"] = {"$regex": query, "$options": "i"}
    sort_field = "rating" if sort == "rating" else "popularity"
    docs = await db.movies.find(q, {"_id": 0}).sort(sort_field, -1).to_list(500)
    return [public_movie(d) for d in docs]


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXP_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def public_user(user: dict) -> dict:
    return {
        "id": str(user["_id"]),
        "name": user.get("name", ""),
        "email": user["email"],
        "role": user.get("role", "user"),
    }


async def get_current_user(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid authentication token")
    user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class RegisterInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class LoginInput(BaseModel):
    email: EmailStr
    password: str


class WatchlistInput(BaseModel):
    movie_id: int
    title: str
    poster_path: Optional[str] = None
    backdrop_path: Optional[str] = None
    vote_average: Optional[float] = None
    release_date: Optional[str] = None
    language_label: Optional[str] = None
    hindi_dubbed: Optional[bool] = False


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@api_router.get("/")
async def root():
    count = await db.movies.count_documents({})
    return {"message": "Maaneymovies API", "movies": count}


# ---------------------------------------------------------------------------
# Movie routes (fixed paths before /movies/{id})
# ---------------------------------------------------------------------------
@api_router.get("/categories")
async def get_categories():
    return HOME_ROWS


@api_router.get("/genres")
async def get_genres():
    names = await db.movies.distinct("genres")
    return [{"id": n, "name": n} for n in sorted(names)]


@api_router.get("/languages")
async def get_languages():
    return [
        {"key": "all", "name": "All"},
        {"key": "en", "name": "English"},
        {"key": "hi", "name": "Hindi"},
    ]


@api_router.get("/movies/trending")
async def trending():
    return await query_movies(sort="popularity")


@api_router.get("/movies/hero")
async def hero():
    movies = await query_movies(sort="popularity")
    return movies[:6]


@api_router.get("/movies/search")
async def search_movies(query: str = Query(...), page: int = 1):
    results = await query_movies(query=query)
    return {"results": results, "page": 1, "total_pages": 1}


@api_router.get("/movies/discover")
async def discover(genre: Optional[str] = None, language: Optional[str] = None, dubbed: bool = False, page: int = 1):
    results = await query_movies(language=language, genre=genre, dubbed=dubbed or None)
    return {"results": results, "page": 1, "total_pages": 1}


@api_router.get("/movies/category/{key}")
async def category(key: str):
    if key == "trending":
        return await query_movies(sort="popularity")
    if key == "hindi":
        return await query_movies(language="hi")
    if key == "hollywood":
        return await query_movies(language="en")
    if key == "dubbed":
        return await query_movies(dubbed=True)
    if key in GENRE_KEYS:
        return await query_movies(genre=GENRE_KEYS[key])
    raise HTTPException(status_code=404, detail="Unknown category")


@api_router.get("/movies/{movie_id}")
async def movie_details(movie_id: int):
    doc = await db.movies.find_one({"id": movie_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Movie not found")
    m = public_movie(doc)
    genre = (doc.get("genres") or [None])[0]
    similar_docs = await db.movies.find(
        {"genres": genre, "id": {"$ne": movie_id}}, {"_id": 0}
    ).sort("popularity", -1).to_list(12) if genre else []
    m["similar"] = [public_movie(d) for d in similar_docs]
    m["runtime"] = doc.get("runtime")
    m["tagline"] = doc.get("tagline")
    m["cast"] = doc.get("cast", [])
    return m


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------
@api_router.post("/auth/register")
async def register(payload: RegisterInput):
    email = payload.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="An account with this email already exists.")
    doc = {
        "name": payload.name.strip(),
        "email": email,
        "password_hash": hash_password(payload.password),
        "role": "user",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    res = await db.users.insert_one(doc)
    doc["_id"] = res.inserted_id
    token = create_token(str(res.inserted_id), email)
    return {"token": token, "user": public_user(doc)}


@api_router.post("/auth/login")
async def login(payload: LoginInput):
    email = payload.email.lower().strip()
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    token = create_token(str(user["_id"]), email)
    return {"token": token, "user": public_user(user)}


@api_router.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return public_user(user)


@api_router.post("/auth/logout")
async def logout(user: dict = Depends(get_current_user)):
    return {"message": "Logged out"}


# ---------------------------------------------------------------------------
# Watchlist routes (per-user)
# ---------------------------------------------------------------------------
@api_router.get("/watchlist")
async def get_watchlist(user: dict = Depends(get_current_user)):
    items = await db.watchlist.find({"user_id": str(user["_id"])}).sort("added_at", -1).to_list(500)
    for it in items:
        it.pop("_id", None)
        poster, backdrop = it.get("poster_path"), it.get("backdrop_path")
        it["poster_url"] = poster if (poster and poster.startswith("http")) else (f"{IMG_BASE}w500{poster}" if poster else None)
        it["backdrop_url"] = backdrop if (backdrop and backdrop.startswith("http")) else (f"{IMG_BASE}original{backdrop}" if backdrop else None)
    return items


@api_router.post("/watchlist")
async def add_watchlist(payload: WatchlistInput, user: dict = Depends(get_current_user)):
    uid = str(user["_id"])
    existing = await db.watchlist.find_one({"user_id": uid, "movie_id": payload.movie_id})
    if existing:
        return {"message": "Already in watchlist"}
    doc = payload.model_dump()
    doc["user_id"] = uid
    doc["added_at"] = datetime.now(timezone.utc).isoformat()
    await db.watchlist.insert_one(doc)
    return {"message": "Added to watchlist"}


@api_router.delete("/watchlist/{movie_id}")
async def remove_watchlist(movie_id: int, user: dict = Depends(get_current_user)):
    await db.watchlist.delete_one({"user_id": str(user["_id"]), "movie_id": movie_id})
    return {"message": "Removed from watchlist"}


# ---------------------------------------------------------------------------
# App wiring
# ---------------------------------------------------------------------------
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def seed_admin():
    existing = await db.users.find_one({"email": ADMIN_EMAIL})
    if existing is None:
        await db.users.insert_one({
            "name": "Admin", "email": ADMIN_EMAIL,
            "password_hash": hash_password(ADMIN_PASSWORD),
            "role": "admin", "created_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info("Seeded admin user")
    elif not verify_password(ADMIN_PASSWORD, existing["password_hash"]):
        await db.users.update_one({"email": ADMIN_EMAIL}, {"$set": {"password_hash": hash_password(ADMIN_PASSWORD)}})


async def seed_movies():
    seed_ids = [m["id"] for m in MOVIES_SEED]
    for m in MOVIES_SEED:
        await db.movies.update_one({"id": m["id"]}, {"$set": m}, upsert=True)
    await db.movies.delete_many({"id": {"$nin": seed_ids}})
    logger.info("Seeded %d movies", len(MOVIES_SEED))


@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    await db.watchlist.create_index([("user_id", 1), ("movie_id", 1)], unique=True)
    await db.movies.create_index("id", unique=True)
    await seed_admin()
    await seed_movies()


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()


if __name__ == "__main__":
    uvicorn.run("index:app", host="0.0.0.0", port=8001, reload=True)
