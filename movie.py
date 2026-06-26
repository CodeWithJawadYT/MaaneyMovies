
"""
============================================================
 MAANEYMOVIES — single-file FastAPI backend (movie.py)
 ------------------------------------------------------------
 Everything in one file: movie catalogue (107 public-domain FULL
 feature films streamed from the Internet Archive), JWT email/
 password auth, and a per-user watchlist (MongoDB).

 HOW TO RUN LOCALLY
   1) Install deps:
        pip install "fastapi[all]" uvicorn motor pyjwt bcrypt pydantic[email] python-dotenv
   2) Make sure MongoDB is running locally (mongodb://localhost:27017)
      or set MONGO_URL / DB_NAME environment variables.
   3) Start the server:
        python movie.py
      (or: uvicorn movie:app --reload --port 8001)
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
# Movie catalogue — 107 FULL feature films (62 Indian + 45 world) from archive.org
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
    # ===================== HOLLYWOOD / ENGLISH CLASSICS =====================
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

    # ===================== INDIAN / HINDI CLASSICS =====================
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

    # ===================== INDIAN GOLDEN-AGE CLASSICS (public domain in India) =====================
    _m(2101, "Awaara", HI, ["Drama", "Romance", "Crime"], 8.0, "1951", 193, 98, ["Hindi"],
       "AwaaraVOSERajKapoor1951", "Awaara%20%28VOSE%20Raj%20Kapoor%2C%201951%29.mp4",
       "A judge's abandoned son, raised in poverty by a criminal, grows up to fall in love with the daughter of the very man who cast out his mother. Raj Kapoor's landmark social drama."),
    _m(2102, "Shree 420", HI, ["Comedy", "Drama", "Romance"], 8.0, "1955", 168, 97, ["Hindi"],
       "shree-420-1955-raj-kapoor", "Shree.420.1955.1080p.WEBRip.x264.AAC-%5BYTS.MX%5D.mp4",
       "A naive graduate arrives in Bombay with honesty as his only asset, only to be seduced by the glamour and corruption of the big city. Raj Kapoor's beloved classic."),
    _m(2103, "Pyaasa", HI, ["Drama", "Romance", "Musical"], 8.3, "1957", 153, 95, ["Hindi"],
       "pyaasa-1957-guru-dutt-hindi-dvd-rip-xvid-smeet", "pyaasa%281957%29%5BGuru%20Dutt%5DHindi-DvdRip-Xvid%20_%20Smeet.mp4",
       "A struggling, unrecognized poet discovers that the world only values his work once it believes he is dead. Guru Dutt's haunting poetic masterpiece."),
    _m(2104, "Do Bigha Zamin", HI, ["Drama"], 8.2, "1953", 131, 94, ["Hindi"],
       "do.-bigha.-zamin.-1953.576p.-mubi.-web-dl.x-264", "Do.Bigha.Zamin.1953.576p.MUBI.WEB-DL.x264.mp4",
       "A poor farmer travels to Calcutta and pulls a rickshaw to save his two acres of land from a greedy landlord. Bimal Roy's neorealist masterpiece."),
    _m(2105, "Gunga Jumna", HI, ["Action", "Drama", "Crime"], 7.8, "1961", 148, 93, ["Hindi"],
       "gunga-jumna-1961", "Gunga%20Jumna%20%281961%29.ia.mp4",
       "Two brothers on opposite sides of the law — one a dacoit, the other a policeman — are torn apart by fate in this dialect-defining Dilip Kumar epic."),
    _m(2106, "Madhumati", HI, ["Romance", "Mystery", "Drama"], 7.8, "1958", 165, 92, ["Hindi"],
       "madhumati-1958-bimal-roy-classic-hindi-film", "VTS_02_2.mp4",
       "An estate manager is haunted by visions of a past life and a lost love in Bimal Roy's atmospheric reincarnation classic, written by Ritwik Ghatak."),
    _m(2107, "Naya Daur", HI, ["Drama", "Musical"], 7.6, "1957", 173, 91, ["Hindi"],
       "naya-daur-1957-hindi..-black-white..-dv-drip.-480p.-x-264.-aac.-5.1.-esubs.-chapters.-by.juleyano",
       "Naya%20Daur%20%281957%29%20Hindi.Colour.DvDRip.720p.%20x264.AAC.5.1.Arabic.ESubs.Chapters.BY.juleyano.mp4",
       "A village tonga driver races a bus to prove man can triumph over machine, uniting his community against industrial greed. Dilip Kumar stars."),
    _m(2108, "Sangam", HI, ["Drama", "Romance"], 7.3, "1964", 238, 90, ["Hindi"],
       "sangam-1964-hindi.-web.-hd.-rip.-720p.x-264.-aac.-arabic.-e.-sub.-by.juleyano",
       "Sangam%20%281964%29%20Hindi.%20WEB.HD.%20Rip.720p.x%20264.%20AAC.%20Arabic.E.Sub.%20BY.juleyano.mp4",
       "Two best friends love the same woman; when one believes the other has died, a love triangle of friendship, sacrifice and jealousy unfolds. Raj Kapoor's first colour film."),
    _m(2109, "Aan", HI, ["Action", "Adventure", "Romance"], 7.0, "1952", 130, 89, ["Hindi"],
       "aan-1952-the-savage-princess-1952-hindi.-dv-drip.-480p.x-264.-ac-3.-esubs.-chapters.-by-juleyano",
       "Aan%20%281952%29%20The%20Savage%20Princess%20%281952%29%20%20Hindi.DvDRip.480p.x264.AC3.Esubs.Chapters.BY%20Juleyano.mp4",
       "A spirited villager tames an arrogant princess and battles a tyrannical prince in India's first Technicolor spectacle, starring Dilip Kumar and Nadira."),
    _m(2110, "Taxi Driver", HI, ["Crime", "Drama", "Romance"], 7.2, "1954", 124, 88, ["Hindi"],
       "taxi-driver-1954-hindi.-dv-drip.-480p.-x-264-ac-3-5.1.-arabic.-esub.-chapters.-by.juleyano",
       "Taxi%20Driver%20%281954%29%20Hindi.DvDRip.480p.%20x264%20AC3%205.1.Arabic.Esub.Chapters.BY.juleyano.mp4",
       "A carefree Bombay taxi driver gets entangled with a runaway singer and a gang of crooks in this breezy Dev Anand noir."),
    _m(2111, "Jagriti", HI, ["Drama", "Family"], 7.5, "1954", 132, 70, ["Hindi"],
       "jagriti-1954-satyen-bose-classic-hindi-film-filmistan-hemant-kumar-abhi-bhattacharya-kavi-pradeep", "VTS_02_1.mp4",
       "A devoted teacher transforms a class of unruly boys through compassion and patriotism in this National Award-winning Filmistan classic."),
    _m(2112, "Sita Sings the Blues", HI, ["Animation", "Musical", "Comedy"], 8.0, "2008", 82, 75, ["English"],
       "Sita_Sings_the_Blues", "Sita_Sings_the_Blues.mp4",
       "The ancient Ramayana retold through the eyes of Sita and set to 1920s jazz — Nina Paley's award-winning, freely-licensed animated musical."),

    # ===================== INDIAN GOLDEN-AGE EXPANSION (public domain in India) =====================
    _m(2201, "Mother India", HI, ["Drama"], 8.0, "1957", None, 80, ["Hindi"],
       "mother-india-1957-hindi-classic-film", "VTS_02_5.mp4",
       "An impoverished mother endures flood, famine and a rebellious son to uphold her honour — Mehboob Khan's epic, India's first Oscar-nominated film."),
    _m(2202, "Mughal-e-Azam", HI, ["Drama", "History", "Romance"], 8.2, "1960", None, 82, ["Hindi"],
       "mughal-e-azam-1960-black-white-full-movie", "Mughal-E-Azam_%E0%A4%AE%E0%A5%81%E0%A4%97%E0%A4%BC%E0%A4%B2-%E0%A4%8F-%E0%A4%86%E0%A4%9C%E0%A4%BC%E0%A4%AE%20%281960%29%20_%20Black%20%26%20White%20full%20movie.mp4",
       "Prince Salim defies his father Emperor Akbar over his love for the courtesan Anarkali, in K. Asif's monumental Mughal romance."),
    _m(2203, "Andaz", HI, ["Drama", "Romance"], 7.3, "1949", None, 73, ["Hindi"],
       "andaz-1949-hindi.-webrip-x-264.-aac-lc.-arabic.-esub.-5.1.-by.juleyano", "Andaz%20%281949%29%20Hindi.WEBRipX264.AAC%20LC.Arabic.ESub.5.1.By.juleyano.mp4",
       "A love triangle turns tragic when a woman's friendly affection is mistaken for love — Mehboob Khan's classic starring Dilip Kumar, Raj Kapoor and Nargis."),
    _m(2204, "Barsaat", HI, ["Drama", "Romance", "Musical"], 7.4, "1949", None, 74, ["Hindi"],
       "barsaat-1949-raj-kapoor-classic-hindi-film-nargis-dutt-nimmi-premnath", "VTS_02_5.mp4",
       "Two friends with very different ideas of love spend a fateful monsoon in the hills, in Raj Kapoor's breakthrough romantic musical."),
    _m(2205, "Baazi", HI, ["Crime", "Thriller", "Drama"], 7.4, "1951", None, 74, ["Hindi"],
       "baazi-1951-classic-hindi-film-dev-anand-kalpana-kartik-guru-dutt-k-n-singh-geeta-bali", "VTS_01_3.mp4",
       "A charming gambler is drawn into the criminal underworld to save his ailing sister — Guru Dutt's stylish debut, a milestone of Hindi noir."),
    _m(2206, "Devdas", HI, ["Drama", "Romance"], 7.7, "1955", None, 77, ["Hindi"],
       "devdas-1955-classic-hindi-film-bimal-roy-dilip-kumar-suchitra-sen-vyjayantimala-shemaroo-dvd", "VTS_02_5.mp4",
       "Unable to marry his childhood love, a heartbroken young man drinks himself toward ruin in Bimal Roy's definitive adaptation of the Sarat Chandra classic."),
    _m(2207, "Boot Polish", HI, ["Drama", "Family"], 7.6, "1954", None, 76, ["Hindi"],
       "boot-polish-1954-hindi.-dv-drip.-480p.-xvi-d-ac-3.-arabic.-esubs.-5.1..-by-juleyano", "Boot%20Polish%20%281954%29%20Hindi.Dv%20DRip.480p.XviD%2CAC3.Arabic.%20Esubs.5.1..%20BY%20Juleyano.mp4",
       "Two orphaned children refuse to beg and shine shoes to survive on the streets of Bombay — a tender Raj Kapoor production."),
    _m(2208, "Chori Chori", HI, ["Comedy", "Romance", "Musical"], 7.6, "1956", None, 76, ["Hindi"],
       "chori-chori-1956-raj-kapoor-nargis-classic-hindi-film", "VTS_01_2.mp4",
       "A runaway heiress and a wisecracking reporter fall in love on the road in this sparkling Raj Kapoor–Nargis musical remake of 'It Happened One Night.'"),
    _m(2209, "Mr. & Mrs. 55", HI, ["Comedy", "Romance"], 7.5, "1955", None, 75, ["Hindi"],
       "mr-mrs-55-1955-guru-dutt-madhubala-classic-hindi-film", "VTS_03_3.mp4",
       "A penniless cartoonist enters a sham marriage with an heiress who must wed to claim her fortune — Guru Dutt's witty romantic comedy."),
    _m(2210, "C.I.D.", HI, ["Crime", "Thriller", "Mystery"], 7.4, "1956", None, 74, ["Hindi"],
       "cid-1956-classic-hindi-film-raj-khosla-dev-anand-waheedah-rehman-shakila-bir-shakuja-guru-dutt", "VTS_02_1.mp4",
       "A police detective hunts a killer while tangling with a glamorous moll in Raj Khosla's slick Bombay crime thriller, starring Dev Anand."),
    _m(2211, "Howrah Bridge", HI, ["Crime", "Thriller", "Musical"], 7.3, "1958", None, 73, ["Hindi"],
       "howrah-bridge-1958-hindi", "VTS_09_2.mp4",
       "A man comes to Calcutta to avenge his brother's murder and recover a stolen family heirloom, amid cabaret nightclubs and smugglers."),
    _m(2212, "Kaagaz Ke Phool", HI, ["Drama", "Romance"], 7.9, "1959", None, 79, ["Hindi"],
       "kagaz-ke-phool", "VTS_01_1.mp4",
       "A celebrated film director's life unravels as fame fades and love slips away — Guru Dutt's hauntingly beautiful, autobiographical masterpiece."),
    _m(2213, "Nau Do Gyarah", HI, ["Comedy", "Crime", "Romance"], 7.2, "1957", None, 72, ["Hindi"],
       "nau-do-gyarah", "VTS_01_4.mp4",
       "A young man on a road trip to claim his inheritance picks up a runaway bride and stumbles into a murder mystery. A breezy Dev Anand caper."),
    _m(2214, "Munimji", HI, ["Drama", "Romance"], 7.0, "1955", None, 70, ["Hindi"],
       "Munimji", "VTS_01_5.mp4",
       "Separated brothers, hidden identities and romance collide in this entertaining Dev Anand–Nalini Jaywant musical drama."),
    _m(2215, "Funtoosh", HI, ["Comedy", "Drama"], 6.9, "1956", None, 69, ["Hindi"],
       "funtoosh-1956-hindi.-dv-drip.-480p.x-264.-aac.-ex-dt-by.juleyano", "Tere%20Ghar%20Ke%20Samne%20%281963%29%20Hindi.DvDRip.480p.x264.AAC.5.1.Chapters.BY%20Juleyano.ia.mp4",
       "A man declared insane is insured for a fortune by a schemer who plans his death — then everything goes comically wrong. Dev Anand stars."),
    _m(2216, "Kala Pani", HI, ["Crime", "Drama", "Mystery"], 7.4, "1958", None, 74, ["Hindi"],
       "kalapani-1958-dev-anand-madhubala-nalini-jaywant-raj-khosla-classic-hindi-film", "VTS_01_2.mp4",
       "A young man works to clear his imprisoned father's name, falling for a journalist as he uncovers the truth. Dev Anand in an acclaimed mystery."),
    _m(2217, "Kala Bazar", HI, ["Crime", "Drama", "Romance"], 7.4, "1960", None, 74, ["Hindi"],
       "kala-bazar-1960-hindi.-web.-rip.-amazon.-480p.x-264.-aac.-esub..-by-juleyano", "Kala%20Bazar%20%281960%29%20Hindi.WEB.Rip.Amazon.480p.x264.AAC.ESub..%20BY%20juleyano.ia.mp4",
       "A cinema black-marketeer selling tickets in the underworld finds his conscience — and love — pulling him toward honesty. Dev Anand stars."),
    _m(2218, "Hum Dono", HI, ["Drama", "Romance", "War"], 7.7, "1961", None, 77, ["Hindi"],
       "hum-dono_202202", "VTS_02_2.mp4",
       "Two soldiers who look identical cross paths at war, and one must face the other's grieving family. A poignant Dev Anand double-role classic."),
    _m(2219, "Tere Ghar Ke Samne", HI, ["Comedy", "Romance"], 7.2, "1963", None, 72, ["Hindi"],
       "tere-ghar-ke-samne-1963-classic-hindi-film-dev-anand-nutan", "VTS_02_3.mp4",
       "An architect falls for the daughter of his father's business rival, building two houses and one romance. A charming Dev Anand–Nutan comedy."),
    _m(2220, "Sahib Bibi Aur Ghulam", HI, ["Drama", "Romance"], 8.2, "1962", None, 82, ["Hindi"],
       "sahib-bibi-aur-ghulam-1962-classic-hindi-film", "VTS_01_4.mp4",
       "The lonely wife of a decadent aristocrat befriends a humble worker as her feudal world crumbles — Guru Dutt's elegant, tragic masterpiece."),
    _m(2221, "Kabuliwala", HI, ["Drama"], 7.8, "1961", None, 78, ["Hindi"],
       "kabuliwala-balraj-sahni-usha-kiran", "Kabuliwala%20-%20Balraj%20Sahni%2C%20Usha%20Kiran.mp4",
       "A Pathan fruit-seller in Calcutta befriends a little girl who reminds him of the daughter he left behind in Afghanistan. Tagore's beloved tale."),
    _m(2222, "Chaudhvin Ka Chand", HI, ["Drama", "Romance", "Musical"], 7.5, "1960", None, 75, ["Hindi"],
       "chaudhvin-ka-chand", "VTS_01_4.mp4",
       "Two friends unknowingly love the same veiled woman, with tender and tragic consequences, in this lyrical Guru Dutt Muslim social."),
    _m(2223, "Anuradha", HI, ["Drama", "Romance", "Musical"], 7.6, "1960", None, 76, ["Hindi"],
       "anuradha-1960-classic-hindi-film-hrishikesh-mukherjee-leela-naidu-balraj-sahni", "VTS_01_4.mp4",
       "A gifted singer sacrifices her career for marriage to a dedicated rural doctor, then questions her choices. Hrishikesh Mukherjee's sensitive drama."),
    _m(2224, "Professor", HI, ["Comedy", "Romance"], 7.0, "1962", None, 70, ["Hindi"],
       "professor_202202", "VTS_02_6.mp4",
       "A young man disguises himself as an elderly tutor to support his ailing mother — and falls for his strict employer's niece. A Shammi Kapoor comedy."),
    _m(2225, "China Town", HI, ["Crime", "Thriller", "Musical"], 6.8, "1962", None, 68, ["Hindi"],
       "china-town-1962-hindi.-dv-drip.-480p.x-264.-aac..-esubs.-5.1.-bw-torrents.-rus.-by.-juleyano", "China%20Town%20%281962%29%20Hindi.DvDRip.480p.x264.AAC..Esubs.5.1.BwTorrents.Rus.By.Juleyano.mp4",
       "A nightclub singer is recruited to impersonate his criminal lookalike to bust a smuggling ring. A stylish Shammi Kapoor double-role thriller."),
    _m(2226, "Bees Saal Baad", HI, ["Horror", "Mystery", "Thriller"], 7.6, "1962", None, 76, ["Hindi"],
       "bees-saal-baad-1962-hindi.-dv-drip.-480p.x-264.-aac.-esubs.-5.1..-chapters.-by-juleyano", "Bees%20Saal%20Baad%20%281962%29%20Hindi.DvDRip.480p.x264.AAC.ESubs.5.1..Chapters.BY%20Juleyano.mp4",
       "A nobleman returning to his ancestral haveli is stalked by a vengeful spirit tied to a twenty-year-old murder. A landmark Hindi horror mystery."),
    _m(2227, "Mere Mehboob", HI, ["Drama", "Romance", "Musical"], 7.3, "1963", None, 73, ["Hindi"],
       "mere-mehboob-1963-hindi.-dv-drip.-480p.x-264.-ac-3..-eng.-sub.-chapters.-phantom-by.juleyano", "Mere%20Mehboob%20%281963%29%20Hindi.DvDRip.480p.x264.AC3..Eng.Sub.Chapters.%20%5BPhantom%5D%20BY.juleyano.mp4",
       "Two lovers separated by circumstance search for each other in old Lucknow, in this opulent Muslim-social musical romance."),
    _m(2228, "Woh Kaun Thi", HI, ["Mystery", "Thriller", "Romance"], 7.8, "1964", None, 78, ["Hindi"],
       "woh-kaun-thi", "VTS_01_5.mp4",
       "A doctor is haunted by a mysterious woman in white who seems to predict death — Raj Khosla's eerie suspense classic with unforgettable songs."),
    _m(2229, "Kohraa", HI, ["Horror", "Mystery", "Thriller"], 7.5, "1964", None, 75, ["Hindi"],
       "kohraa-1964-hindi.-1-cd.-dv-drip.-480p.x-264.-ac-3.-esub.-dude-lu-ci-fe-r-ex-dt.-by.juleyano", "Kohraa%20%281964%29%20Hindi.1CD.DvDRip.480p.x264.AC3.Esub.%5BDudeLuCiFeR%5D%20%5BExDT%5D.BY.juleyano.mp4",
       "A new bride at a brooding mansion is tormented by the ghostly presence of her husband's late first wife. A gothic Hindi reworking of 'Rebecca.'"),
    _m(2230, "Aar Paar", HI, ["Crime", "Comedy", "Musical"], 7.5, "1954", None, 75, ["Hindi"],
       "aar-paar-1954-guru-dutt-classic-hindi-film-shyama-jagdish-sethi-johnny-walker", "VTS_02_2.mp4",
       "A roguish taxi driver romances a garage owner's daughter and gets caught up with crooks, in Guru Dutt's snappy, song-filled crime comedy."),
    _m(2231, "Baiju Bawra", HI, ["Drama", "Musical", "Romance"], 7.6, "1952", None, 76, ["Hindi"],
       "BaijuBawra1952", "Baiju%20Bawra%20%281952%29%20Meena%20Kumari%2C%20Bharat%20Bhushan.mp4",
       "A musician trains for years to defeat the emperor's court singer Tansen and avenge his father, in this classical-music romantic epic."),
    _m(2232, "Albela", HI, ["Comedy", "Musical", "Romance"], 7.0, "1951", None, 70, ["Hindi"],
       "albela-1951-classic-hindi-film-bhagwan-dada-geeta-bali", "VTS_01_1.mp4",
       "A stage-struck young man chases showbiz dreams with the help of a famous actress, in this hugely popular musical comedy."),
    _m(2233, "Anarkali", HI, ["Drama", "History", "Romance"], 7.0, "1953", None, 70, ["Hindi"],
       "anarkali-1953-filmistan-hindi-classic", "VTS_01_5.mp4",
       "The doomed love of a court dancer and the Mughal prince Salim, defied by Emperor Akbar — a lavish historical romance."),
    _m(2234, "Jagte Raho", HI, ["Drama", "Comedy"], 8.0, "1956", None, 80, ["Hindi"],
       "jagte-raho-1956-hindi..-dv-drip.-480p.-x-264.-ac-3-.-esubs.-5.1.-chapters.-by-juleyano", "Jagte%20Raho%20%281956%29%20Hindi..DvDRip.480p.X264.AC3%20.ESubs.5.1.Chapters.BY%20Juleyano.mp4",
       "A thirsty villager wanders into a city apartment block at night and exposes the hypocrisy of its 'respectable' residents. Raj Kapoor's biting fable."),
    _m(2235, "Jhanak Jhanak Payal Baaje", HI, ["Drama", "Musical", "Romance"], 7.3, "1955", None, 73, ["Hindi"],
       "jhanak-jhanak-payal-baaje", "JHANAK_JHANAK_PAYAL_BAAJE.mp4",
       "A classical dancer and a young woman find love through art against her family's wishes, in V. Shantaram's pioneering colour dance film."),
    _m(2236, "Jhumroo", HI, ["Comedy", "Musical", "Romance"], 7.0, "1961", None, 70, ["Hindi"],
       "jhumroo-1961-classic-hindi-film-kishore-kumar-madhubala-shanker-mukerji", "VTS_01_4.mp4",
       "A carefree hill-country youth uncovers family secrets and finds romance, in this Kishore Kumar musical comedy he also composed."),
    _m(2237, "Patita", HI, ["Drama", "Romance"], 6.8, "1953", None, 68, ["Hindi"],
       "patita-1953-hindi.-web.-dl.-720p.-zee-5.x-264.-aac.-5.1.-esubs.-by.juleyano", "Patita%20%281953%29%20Hindi.WEB.DL.720p.ZEE5.x264.AAC.5.1.ESubs.BY.juleyano.mp4",
       "A man falls in love with a woman shunned by society for her past, and must overcome his own prejudice. A socially conscious Dev Anand drama."),
    _m(2238, "Insaan Jaag Utha", HI, ["Drama", "Crime"], 6.8, "1959", None, 68, ["Hindi"],
       "insaan-jaag-utha-1959-hindi.-webrip.-480p.-x-264.-aac..-arabic.-esubs.-by.juleyano", "Insaan%20Jaag%20Utha%20%281959%29%20Hindi.NTSC.DvDRip.480p.%20x264.AAC..BY.juleyano.mp4",
       "Workers at a dam site confront a fugitive and their own fears, in this Bimal Roy-produced drama starring Sunil Dutt and Madhubala."),
    _m(2239, "Pather Panchali", HI, ["Drama"], 8.3, "1955", None, 83, ["Bengali"],
       "PatherPanchali1955720p", "Pather%20Panchali%20%281955%29%20%5B720p%5D.mp4",
       "In a Bengal village, a poor family's children Apu and Durga discover wonder and sorrow — Satyajit Ray's transcendent debut and world-cinema landmark."),
    _m(2240, "Aparajito", HI, ["Drama"], 8.1, "1956", None, 81, ["Bengali"],
       "Aparajito1956720p", "Aparajito%20%281956%29%20%5B720p%5D.mp4",
       "The second chapter of the Apu trilogy follows the boy's coming of age and his bond with his mother as he leaves the village for the city."),
    _m(2241, "Jalsaghar", HI, ["Drama", "Musical"], 8.0, "1958", None, 80, ["Bengali"],
       "jalsaghar-the-music-room-1958_202209", "VTS_01_0.mp4",
       "A decaying aristocrat clings to his passion for music, hosting one last extravagant concert in his crumbling mansion. Ray's elegiac chamber piece."),
    _m(2242, "Devi", HI, ["Drama"], 7.9, "1960", None, 79, ["Bengali"],
       "devi_20201207", "Devi.mp4",
       "A young woman is declared a living goddess by her devout father-in-law, with devastating results, in Satyajit Ray's searching critique of faith."),
    _m(2243, "Charulata", HI, ["Drama", "Romance"], 8.2, "1964", None, 82, ["Bengali"],
       "charulata-1964-720p", "Charulata%20%281964%29%20%5B720p%5D.mp4",
       "A lonely, intelligent wife in 19th-century Bengal grows close to her husband's cousin, in Satyajit Ray's exquisitely tender masterpiece."),
    _m(2244, "Parash Pathar", HI, ["Comedy", "Fantasy"], 7.6, "1958", None, 76, ["Bengali"],
       "parashpathar1958", "VTS_02_3.mp4",
       "A mild clerk finds a stone that turns metal to gold and discovers riches bring chaos, in Satyajit Ray's delightful satirical comedy."),
    _m(2245, "Mayabazar", HI, ["Fantasy", "Drama", "Mythology"], 8.6, "1957", None, 86, ["Telugu"],
       "mayabazar-1957-1080p-hq-bluray-x-264-avc-telugu-dd-5", "Mayabazar_1957_1080p_HQ_BLURAY_x264_AVC_Telugu_DD%2B_5.mp4",
       "Krishna and Ghatotkacha use illusion and wit to unite young lovers against scheming relatives — the most beloved fantasy of Indian cinema."),
    _m(2246, "Parasakthi", HI, ["Drama"], 7.8, "1952", None, 78, ["Tamil"],
       "sivajimovies-parasakthi-1952", "%40SIVAJIMOVIES%20Parasakthi%201952.mp4",
       "A family is torn apart by poverty and injustice, in a fiery social drama that launched Sivaji Ganesan and shook Tamil cinema."),

    # ===================== MORE WORLD PUBLIC-DOMAIN CLASSICS =====================
    _m(1101, "Scarlet Street", EN, ["Crime", "Thriller", "Drama"], 7.8, "1945", 102, 56, ["English"],
       "ScarletStreet", "Scarlet_Street.mp4",
       "A meek cashier is manipulated by a femme fatale and her schemer boyfriend into a spiral of fraud and murder. Fritz Lang's pitch-black noir."),
    _m(1102, "Meet John Doe", EN, ["Drama", "Comedy", "Romance"], 7.6, "1941", 122, 55, ["English"],
       "meet_john_doe", "meet_john_doe.mp4",
       "A newspaper invents a folk hero who threatens to take his own life in protest of society's ills — until the man hired to play him is swept up in the movement. Frank Capra directs."),
    _m(1103, "Horror Express", EN, ["Horror", "Sci-Fi", "Thriller"], 6.7, "1972", 88, 54, ["English"],
       "Horror_Express", "Horror_Express.mp4",
       "Aboard the Trans-Siberian Express, scientists discover a frozen creature whose deadly secret begins killing the passengers. Christopher Lee and Peter Cushing star."),
    _m(1104, "Impact", EN, ["Crime", "Thriller", "Drama"], 6.9, "1949", 111, 53, ["English"],
       "impact", "impact.mp4",
       "Left for dead by his cheating wife's murder plot, a businessman quietly builds a new life — and a case for revenge. A twisty 1949 film noir."),
    _m(1105, "Quicksand", EN, ["Crime", "Thriller"], 6.5, "1950", 79, 52, ["English"],
       "Quicksand_clear", "Quicksand.mp4",
       "A car mechanic borrows twenty dollars and tumbles into a nightmare of blackmail and crime. Mickey Rooney stars in this tense film noir."),
    _m(1106, "Royal Wedding", EN, ["Comedy", "Romance", "Musical"], 6.8, "1951", 93, 51, ["English"],
       "royal_wedding", "royal_wedding.mp4",
       "A brother-and-sister dance act finds romance in London during the royal wedding of 1947 — featuring Fred Astaire's famous dancing-on-the-ceiling number."),
    _m(1107, "The Ghoul", EN, ["Horror", "Thriller"], 6.2, "1933", 79, 50, ["English"],
       "TheGhoul", "TheGhoul_1933.mp4",
       "An Egyptologist returns from the grave to take vengeance on those who stole his sacred jewel. Boris Karloff stars in this gothic British chiller."),
    _m(1108, "Inner Sanctum", EN, ["Thriller", "Horror"], 5.8, "1948", 62, 49, ["English"],
       "Inner_Sanctum_movie", "Inner_Sanctum.mp4",
       "A man who pushes a woman to her death is trapped at a remote railway boarding house as suspicion closes in. A moody poverty-row thriller."),
    _m(1109, "Charlie Chaplin Festival", EN, ["Comedy"], 7.5, "1938", 60, 48, ["Silent"],
       "charlie_chaplin_film_fest", "charlie_chaplin_film_fest.mp4",
       "A collection of Charlie Chaplin's classic silent comedy shorts — the Little Tramp at his slapstick best."),
    _m(1110, "The Gun and the Pulpit", EN, ["Western", "Action"], 5.5, "1974", 74, 47, ["English"],
       "cco_thegunandthepulpit", "ccoPublicDomainThe_Gun_and_the_Pulpit.mp4",
       "A wanted gunslinger poses as a preacher in a town terrorized by a land baron — and decides to fight back. A breezy TV-movie Western."),
    _m(1111, "The Fast and the Furious", EN, ["Action", "Crime", "Thriller"], 5.3, "1955", 73, 46, ["English"],
       "TheFastandtheFuriousJohnIreland1954goofyrip", "TheFastandtheFuriousJohnIreland1954goofyrip.mp4",
       "A man wrongly accused of murder takes a woman hostage and enters a cross-border sports-car race to escape the police. The Roger Corman original."),
    _m(1112, "Teenagers from Outer Space", EN, ["Sci-Fi", "Horror"], 4.2, "1959", 86, 45, ["English"],
       "teenagers_from_outerspace", "Teenagers_from_Outer_Space.mp4",
       "An alien scout rebels against his people's plan to farm giant monsters on Earth, falling for a local girl. Endearingly cheap 1950s sci-fi."),
    _m(1113, "Killers from Space", EN, ["Sci-Fi", "Horror"], 4.0, "1954", 71, 44, ["English"],
       "Killers_from_space", "Killers_from_space.mp4",
       "A scientist survives a plane crash only to be controlled by bug-eyed aliens plotting to conquer Earth. Peter Graves stars in this atomic-age B-movie."),
    _m(1114, "Voyage to the Planet of Prehistoric Women", EN, ["Sci-Fi", "Adventure"], 3.8, "1968", 78, 43, ["English"],
       "VoyagetothePlanetofPrehistoricWomen", "VoyagetothePlanetofPrehistoricWomen.mp4",
       "Astronauts land on Venus and encounter telepathic alien women and prehistoric beasts in this gloriously strange cult sci-fi."),
    _m(1115, "Return of the Kung Fu Dragon", EN, ["Action", "Adventure", "Fantasy"], 4.5, "1976", 90, 42, ["English"],
       "Return_of_the_Kung_Fu_Dragon", "Return_of_the_Kung_Fu_Dragon.mp4",
       "When a kingdom falls to a tyrant, a lost princess and a band of martial artists rise to reclaim it in this colourful kung-fu fantasy."),
    _m(1116, "War of the Robots", EN, ["Sci-Fi", "Adventure"], 3.5, "1978", 99, 41, ["English"],
       "WarOfTheRobots", "WarOfTheRobots1978.mp4",
       "Alien androids abduct two scientists and a spaceship crew gives chase across the galaxy in this Italian space-opera romp."),
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


def public_movie(m: dict) -> dict:
    poster = m.get("poster")
    poster_url = poster if (poster and poster.startswith("http")) else ((IMG_BASE + "w500" + poster) if poster else None)
    backdrop = m.get("backdrop")
    backdrop_url = backdrop if (backdrop and backdrop.startswith("http")) else ((IMG_BASE + "original" + backdrop) if backdrop else None)
    return {
        "id": m["id"], "title": m["title"], "year": m.get("year"),
        "release_date": str(m.get("year", "")) + "-01-01" if m.get("year") else None,
        "language": m.get("language"),
        "language_label": "Hindi" if m.get("language") == "hi" else "English",
        "genres": m.get("genres", []), "vote_average": m.get("rating"),
        "overview": m.get("overview"), "poster_path": m.get("poster"),
        "poster_url": poster_url, "backdrop_path": m.get("backdrop"),
        "backdrop_url": backdrop_url, "trailer_key": m.get("trailer"),
        "video_url": m.get("video_url"), "audio": m.get("audio", ["English"]),
        "hindi_dubbed": m.get("hindi_dubbed", False), "popularity": m.get("popularity", 0),
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


# ---------------- Auth helpers ----------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_token(user_id: str, email: str) -> str:
    payload = {"sub": user_id, "email": email,
               "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXP_DAYS)}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def public_user(user: dict) -> dict:
    return {"id": str(user["_id"]), "name": user.get("name", ""),
            "email": user["email"], "role": user.get("role", "user")}


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


# ---------------- Models ----------------
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


# ---------------- Routes ----------------
@api_router.get("/")
async def root():
    count = await db.movies.count_documents({})
    return {"message": "Maaneymovies API", "movies": count}


@api_router.get("/categories")
async def get_categories():
    return HOME_ROWS


@api_router.get("/genres")
async def get_genres():
    names = await db.movies.distinct("genres")
    return [{"id": n, "name": n} for n in sorted(names)]


@api_router.get("/languages")
async def get_languages():
    return [{"key": "all", "name": "All"}, {"key": "en", "name": "English"}, {"key": "hi", "name": "Hindi"}]


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


@api_router.post("/auth/register")
async def register(payload: RegisterInput):
    email = payload.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="An account with this email already exists.")
    doc = {"name": payload.name.strip(), "email": email,
           "password_hash": hash_password(payload.password), "role": "user",
           "created_at": datetime.now(timezone.utc).isoformat()}
    res = await db.users.insert_one(doc)
    doc["_id"] = res.inserted_id
    return {"token": create_token(str(res.inserted_id), email), "user": public_user(doc)}


@api_router.post("/auth/login")
async def login(payload: LoginInput):
    email = payload.email.lower().strip()
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    return {"token": create_token(str(user["_id"]), email), "user": public_user(user)}


@api_router.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return public_user(user)


@api_router.post("/auth/logout")
async def logout(user: dict = Depends(get_current_user)):
    return {"message": "Logged out"}


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
    if await db.watchlist.find_one({"user_id": uid, "movie_id": payload.movie_id}):
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


# ---------------- App wiring ----------------
app.include_router(api_router)
app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=CORS_ORIGINS,
                   allow_methods=["*"], allow_headers=["*"])


async def seed_admin():
    existing = await db.users.find_one({"email": ADMIN_EMAIL})
    if existing is None:
        await db.users.insert_one({"name": "Admin", "email": ADMIN_EMAIL,
            "password_hash": hash_password(ADMIN_PASSWORD), "role": "admin",
            "created_at": datetime.now(timezone.utc).isoformat()})
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
    uvicorn.run("movie:app", host="0.0.0.0", port=8001, reload=True)