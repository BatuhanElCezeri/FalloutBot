# Buildpacks
# https://github.com/jonathanong/heroku-buildpack-ffmpeg-latest.git
# https://github.com/xrisk/heroku-opus.git
import asyncio
import discord
import youtube_dl
import random
import itertools
import time
import os
from discord.ext import commands
from youtube_search import YoutubeSearch

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    # 'source_address': '0.0.0.0'
}

ffmpeg_options = {
    'options': '-vn'
}

player_emojis = {
    'stop': u'\u23F9',
    'play_pause': u'\u23EF',
    'next_track': u'\u23ED',
    'backward': u'\u21AA',
    'forward': u'\u21A9'
}

playlist_emojis = {
    'dislike': u'\U0001F44E',
    'like': u'\U0001F44D'
}

# if not discord.opus.is_loaded():
#     discord.opus.load_opus('opus')
# ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

youtube_dl.utils.bug_reports_message = lambda: ''


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('webpage_url')
        self.thumbnail = data.get('thumbnail')
        self.uploader = data.get('uploader')
        self.duration = data.get('duration')
        self.start_time = data.get('start_time')
        self.filename = data.get('filename')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False, start_time=0):
        loop = loop or asyncio.get_event_loop()
        try:
            with youtube_dl.YoutubeDL(ytdl_format_options) as ytdl:
                data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        except youtube_dl.utils.DownloadError as error:
            print(error)
            return
        if 'entries' in data:
            data = data['entries'][0]
        with youtube_dl.YoutubeDL(ytdl_format_options) as ytdl:
            filename = data['url'] if stream else ytdl.prepare_filename(data)
        data['filename'] = filename
        data['start_time'] = start_time
        data['duration'] = time.strftime('%M:%S', time.gmtime(data.get('duration')))
        if start_time != 0:
            ffmpeg_options['options'] = '-vn -ss {}'.format(time.strftime('%M:%S', time.gmtime(start_time)))
        else:
            ffmpeg_options['options'] = '-vn'
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)


# TODO:
#  DJ ROLE
#  SPOTIFY CONNECTION
#  CLEAR QUEUE METHOD
class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.handlers = {}

    def get_random_playlist(self):
        conn = self.bot.get_pymysql_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT url, dislike, like_count FROM playlist")
                data = cursor.fetchall()
        finally:
            conn.close()
        db_playlist = [t for t in data]
        db_playlist = [(url, int(like / dislike)) for url, dislike, like in db_playlist]
        print('Random playlist length: {}'.format(len(db_playlist)))
        return db_playlist

    @commands.command(help='Joins authors voice channel.')
    async def join(self, ctx, *, channel: discord.VoiceChannel = None):
        if ctx.voice_client:
            return await ctx.voice_client.move_to(channel)
        if channel is None:
            return await ctx.author.voice.channel.connect()
        await channel.connect()

    @commands.command(help="Downloads audio from a url.")
    async def download(self, ctx, *, url):
        async with ctx.typing():
            print('Requested: {}'.format(url))
            player = await YTDLSource.from_url(url, loop=self.bot.loop)
            if player is None:
                return await ctx.send('Bir şeyler yanlış. Bir daha dene')
            _file = discord.File(open(player.filename, "rb"), filename=player.title)
            await ctx.send(content="İndirilen dosya: ", file=_file)
            try:
                os.remove(player.filename)
            finally:
                print("Deleted {}".format(player.filename))

    @commands.command(help="Streams from a url. Doesn't predownload.")
    async def stream(self, ctx, *, url):
        async with ctx.typing():
            player = await YTDLSource.from_url(url, loop=self.bot.loop, stream=True)
            if player is None:
                return await ctx.send('Birşeyler yanlış. Bir daha dene')
            # sıraya ekle
            await self.handlers[ctx.guild.id].queue.put((ctx, player))
            if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
                embed = self.handlers[ctx.guild.id].last_message.embeds[0]
                embed.add_field(name=str(self.handlers[ctx.guild.id].queue.qsize()),
                                value=player.title)
                await self.handlers[ctx.guild.id].manage_last(await ctx.send(embed=embed))
                for _ in player_emojis.values():
                    await self.handlers[ctx.guild.id].last_message.add_reaction(_)

    @commands.command(help='Plays the first result from a search string.')
    async def play(self, ctx, *, search_string):
        start = time.process_time()
        async with ctx.typing():
            result = YoutubeSearch(search_string, max_results=1).to_dict()
            try:
                url = 'https://www.youtube.com' + result[0]['url_suffix']
            except IndexError:
                return await ctx.send('Video bulamadım. Bir daha dene')
            player = await YTDLSource.from_url(url, loop=self.bot.loop)
            if player is None:
                return await ctx.send('Bir şeyler yanlış. Bir daha dene')
            print('play: Half way in')
            await self.handlers[ctx.guild.id].queue.put((ctx, player))
            print('Queue put successful')
            if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
                embed = self.handlers[ctx.guild.id].last_message.embeds[0]
                embed.add_field(name=str(self.handlers[ctx.guild.id].queue.qsize()),
                                value=player.title)
                await self.handlers[ctx.guild.id].manage_last(await ctx.send(embed=embed))
                for _ in player_emojis.values():
                    await self.handlers[ctx.guild.id].last_message.add_reaction(_)
        print('Method: {} | Elapsed time: {}'.format('play', time.process_time() - start))

    @commands.command(help='Searches youtube. 10 results')
    async def search(self, ctx, *, search_string):
        start = time.process_time()
        self.handlers[ctx.guild.id].search_list.clear()
        results = YoutubeSearch(search_string, max_results=10).to_dict()
        embed = discord.Embed(colour=0x8B0000)
        i = 1
        for _ in results:
            k = '[{} - {}](https://www.youtube.com{})'
            embed.add_field(name=' - '.join([str(i), _['title']]),
                            value=k.format(_['channel'], _['duration'], _['url_suffix']))
            self.handlers[ctx.guild.id].search_list.append('https://www.youtube.com{}'.format(_['url_suffix']))
            i = i + 1
        async with ctx.typing():
            await ctx.send(embed=embed, delete_after=20)
        if self.bot.get_cog('Events'):
            self.bot.remove_cog('Events')
        self.bot.add_cog(Events(self.bot, ctx))
        print('Method: {} | Elapsed time: {}'.format('search', time.process_time() - start))

    @commands.command(help='Plays random songs')
    async def playrandom(self, ctx):
        async with ctx.typing():
            if not ctx.voice_client.is_playing() or not ctx.voice_client.is_paused():
                if not self.handlers[ctx.guild.id].play_random:
                    player = await YTDLSource.from_url(self.handlers[ctx.guild.id].get_song_from_rnd_playlist(),
                                                       loop=self.bot.loop,
                                                       stream=True)
                    if player is None:
                        return await ctx.send('Bir şeyler yanlış. Bir daha dene')
                    await self.handlers[ctx.guild.id].queue.put((ctx, player))
            self.handlers[ctx.guild.id].play_random = not self.handlers[ctx.guild.id].play_random
            if self.handlers[ctx.guild.id].last_message:
                _embed = self.handlers[ctx.guild.id].last_message.embeds[0]
                footer = 'Ozan: Yerli ve Milli İlk Video Oynatıcısı - Rastgele çalma {} ({}) - {}'
                _embed.set_footer(text=footer.format('açık' if self.handlers[ctx.guild.id].play_random else 'kapalı',
                                                     len(self.handlers[ctx.guild.id].static_random_playlist),
                                                     self.bot.version_name))
                await self.handlers[ctx.guild.id].last_message.edit(embed=_embed)

    @commands.command(help='Changes volume to the value.')
    async def volume(self, ctx, volume: int):
        await ctx.message.delete()
        if ctx.voice_client is None:
            return await ctx.send('Ses kanalına bağlı değilim.')

        ctx.voice_client.source.volume = volume / 100
        await ctx.send('Ses seviyesi %{} oldu.'.format(volume))

    @commands.command(help='Pauses')
    async def pause(self, ctx):
        if ctx.voice_client and ctx.voice_client.source:
            ctx.voice_client.pause()
            embed = self.handlers[ctx.guild.id].last_message.embeds[0]
            embed.description = 'Durduruldu'
            await self.handlers[ctx.guild.id].last_message.edit(embed=embed)

    @commands.command(help='Resumes')
    async def resume(self, ctx):
        if ctx.voice_client is not None and ctx.voice_client.source:
            ctx.voice_client.resume()
            embed = self.handlers[ctx.guild.id].last_message.embeds[0]
            embed.description = 'Oynatılıyor'
            await self.handlers[ctx.guild.id].last_message.edit(embed=embed)

    @commands.command(help='Skips current video.')
    async def skip(self, ctx):
        if ctx.voice_client.source:
            ctx.voice_client.stop()

    @commands.command(help='Disconnects the bot from voice channel.')
    async def stop(self, ctx):
        handler = self.handlers.get(ctx.guild.id)
        if handler is not None:
            handler.play_random = False
            handler.refresh_playlist()
            for _ in range(handler.queue.qsize()):
                handler.queue.get_nowait()
                handler.queue.task_done()
            if handler.task:
                handler.task.cancel()
        try:
            await ctx.voice_client.disconnect()
        except AttributeError as error:
            print(error)
        await self.bot.default_presence()

    @commands.command(help='Adds song to bot playlist')
    async def add_link(self, ctx, url: str):
        try:
            with youtube_dl.YoutubeDL(ytdl_format_options) as ytdl:
                data = await self.bot.loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
        except youtube_dl.utils.DownloadError as error:
            print(error)
            return await ctx.send('Yanlış bir şeyler oldu.')
        added_songs = []
        failed_songs = []
        conn = self.bot.get_pymysql_connection()
        try:
            if 'entries' in data:
                entries = [_ for _ in data.get('entries')]
            else:
                entries = [data]
            for entry in entries:
                if entry.get('webpage_url') in self.handlers[ctx.guild.id].static_random_playlist:
                    await ctx.send('Bu şarkı listede var: {}'.format(entry.get('title')))
                    continue
                with conn.cursor() as cursor:
                    cursor.execute('INSERT INTO playlist (url) VALUES ("{}")'.format(entry.get('webpage_url')))
                    conn.commit()

                    cursor.execute('SELECT url FROM playlist where url="{}"'.format(entry.get('webpage_url')))
                    data = cursor.fetchone()

                if data:
                    added_songs.append(entry.get('title'))
                else:
                    failed_songs.append(entry.get('title'))
        finally:
            conn.close()
            await ctx.send('Eklenen şarkılar:\n'
                           '```{}```'.format('\n'.join(added_songs)))
            if len(failed_songs) > 0:
                await ctx.send('\nBaşına bir şey gelen şarkılar:\n'
                               '```{}```'.format('\n'.join(failed_songs)))
            self.handlers[ctx.guild.id].refresh_playlist()

        # if len(url) != 43 or not url.startswith('https://www.youtube.com/watch?v='):
        #     return await ctx.send('Linkini kontrol et. Tam link atmalısın')
        # if url in self._random_playlist:
        #     return await ctx.send('Bu şarkı listede var.')
        # conn = pymysql.connect(HOST, USER_ID, PASSWORD, DATABASE_NAME)
        # try:
        #     with conn.cursor() as cursor:
        #
        #         cursor.execute('INSERT INTO playlist (url) VALUES ("{}")'.format(url))
        #         conn.commit()
        #
        #         cursor.execute('SELECT url FROM playlist where url="{}"'.format(url))
        #         data = cursor.fetchone()
        #
        #     if data:
        #         self.refresh_playlist()
        #         await ctx.send('Şarkı eklendi. Teşekkürler')
        #     else:
        #         await ctx.send('Şarkı eklenemedi.')
        # finally:
        #     conn.close()

    @commands.command(help='Go to the time on the video')
    async def goto(self, ctx, target_time: int):
        async with ctx.typing():
            self.handlers[ctx.guild.id].time_cursor = target_time
            ctx.voice_client.pause()
            player = await YTDLSource.from_url(url=ctx.voice_client.source.url,
                                               loop=self.bot.loop,
                                               start_time=target_time)
            ctx.voice_client.source = player
            self.handlers[ctx.guild.id].source_start_tme = time.time()
            await self.handlers[ctx.guild.id].send_player_embed(player)
            for _ in range(self.handlers[ctx.guild.id].queue.qsize() - 1):
                a = self.handlers[ctx.guild.id].queue.get_nowait()
                self.handlers[ctx.guild.id].queue.task_done()
                self.handlers[ctx.guild.id].queue.put_nowait(a)

    @commands.command(help='Set backward forward time value')
    async def set_skip_time(self, ctx, time_set: int):
        async with ctx.typing():
            self.handlers[ctx.guild.id].time_setting = time_set

    # TODO: Write this method
    @commands.command(help='Switch fancy player message format')
    async def fancy_player(self, ctx):
        pass

    @goto.before_invoke
    async def ensure_source(self, ctx):
        if ctx.voice_client.source is None:
            await ctx.send('Ortada ileri alınacak video yok.')
            raise commands.CommandError('Audio source empty.')

    @stream.before_invoke
    @play.before_invoke
    @search.before_invoke
    @playrandom.before_invoke
    async def ensure_voice(self, ctx):
        if ctx.voice_client is None:
            if ctx.author.voice:
                await ctx.author.voice.channel.connect()
                self.handlers[ctx.guild.id] = Handler(self.bot, ctx)
                self.handlers[ctx.guild.id].create_task()
            else:
                await ctx.send('Ses kanalında değilsin.')
                raise commands.CommandError('Author not connected to a voice channel.')

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user.bot:
            return
        guild_id = reaction.message.guild.id
        if reaction.message.id == self.handlers[guild_id].last_message.id:
            if reaction.emoji == player_emojis['next_track']:
                return await self.handlers[guild_id].static_ctx.invoke(self.bot.get_command('skip'))
            if reaction.emoji == player_emojis['play_pause']:
                return await self.handlers[guild_id].static_ctx.invoke(self.bot.get_command('pause'))
            if reaction.emoji == player_emojis['stop']:
                return await self.handlers[guild_id].static_ctx.invoke(self.bot.get_command('stop'))
            if reaction.emoji == player_emojis['backward']:
                delta_time = time.time() - self.handlers[guild_id].source_start_tme
                target_time = self.handlers[guild_id].time_cursor + delta_time - self.handlers[guild_id].time_setting
                return await self.handlers[guild_id].static_ctx.invoke(self.bot.get_command('goto'),
                                                                       target_time=target_time)
            if reaction.emoji == player_emojis['forward']:
                delta_time = time.time() - self.handlers[guild_id].source_start_tme
                target_time = self.handlers[guild_id].time_cursor + delta_time + self.handlers[guild_id].time_setting
                return await self.handlers[guild_id].static_ctx.invoke(self.bot.get_command('goto'),
                                                                       target_time=target_time)
            if reaction.emoji == playlist_emojis['dislike']:
                self.handlers[guild_id].dislike()
                return await self.handlers[guild_id].static_ctx.invoke(self.bot.get_command('skip'))
            if reaction.emoji == playlist_emojis['like']:
                await self.handlers[guild_id].like()

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction, user):
        if user.bot:
            return
        guild_id = reaction.message.guild.id
        if reaction.message.id == self.handlers[guild_id].last_message.id:
            if reaction.emoji == player_emojis['play_pause']:
                return await self.handlers[guild_id].static_ctx.invoke(self.bot.get_command('resume'))


class Events(commands.Cog):
    def __init__(self, bot, ctx):
        self.bot = bot
        self._ctx = ctx

    @property
    def ctx(self):
        return self._ctx

    @commands.Cog.listener()
    async def on_message(self, msg):
        if msg.author == self.bot.user:
            return
        try:
            index = int(msg.content)
        except ValueError:
            return
        if index < 1 or 10 < index:
            return
        music = self.bot.get_cog('Music')
        await self.ctx.invoke(music.bot.get_command('stream'), url=music.search_list[index - 1])
        music.search_list.clear()
        self.bot.remove_cog('Events')


class Handler:
    def __init__(self, bot, ctx):
        self._ctx = ctx
        self._random_playlist = []
        self.bot = bot
        self.queue = asyncio.Queue(loop=bot.loop)
        self.play_next = asyncio.Event(loop=bot.loop)
        self.play_random = False
        self.last_message = None
        self.task = None
        self.search_list = []
        self.source_start_tme = None
        self.time_cursor = None
        self.time_setting = 30
        self.random_playlist = []
        self.refresh_playlist()

    @property
    def ctx(self):
        return self._ctx

    def create_task(self):
        self.task = self.bot.loop.create_task(self.audio_player())

    def refresh_playlist(self):
        self._random_playlist = self.bot.get_random_playlist()
        self.random_playlist = self._random_playlist.copy()

    def toggle_next(self):
        self.bot.loop.call_soon_threadsafe(self.play_next.set)

    async def send_player_embed(self, source):
        if source.start_time != 0:
            description = 'Şimdi oynatılıyor - {} dan başladı'.format(time.strftime('%M:%S',
                                                                                    time.gmtime(source.start_time)))
        else:
            description = 'Şimdi oynatılıyor'
        embed = discord.Embed(title='{0.title} ({0.duration}) by {0.uploader}'.format(source),
                              url=source.url,
                              description=description,
                              colour=0x8B0000)
        embed.set_thumbnail(url=source.thumbnail)
        footer = 'Ozan: Yerli ve Milli İlk Video Oynatıcısı - Rastgele çalma {} ({}) - {}'
        embed.set_footer(text=footer.format('açık' if self.play_random else 'kapalı',
                                            len(self._random_playlist),
                                            self.bot.version_name))
        if self.last_message:
            _embed = self.last_message.embeds[0]
            if len(_embed.fields) > 1:
                _embed.remove_field(0)
                for _ in _embed.fields:
                    embed.add_field(name=str(self.queue.qsize()),
                                    value=_.value)
        await self.manage_last(await self.ctx.send(embed=embed))
        if self.play_random:
            for _ in playlist_emojis.values():
                await self.last_message.add_reaction(_)
        for _ in player_emojis.values():
            await self.last_message.add_reaction(_)

    async def manage_last(self, msg):
        try:
            if self.last_message:
                await self.last_message.delete()
        finally:
            self.last_message = msg

    def get_song_from_rnd_playlist(self):
        if len(self.random_playlist) == 0:
            self.refresh_playlist()
        cum_weights = list(itertools.accumulate([rating for url, rating in self.random_playlist]))
        song = random.choices(self.random_playlist, cum_weights=cum_weights, k=1)[0]
        self.random_playlist.remove(song)
        return song[0]

    async def audio_player(self):
        try:
            print('Started audio player in channel name: {}'.format(self.ctx.voice_client.channel.name))
            while True:
                self.play_next.clear()
                self.time_cursor = 0

                try:
                    if self.queue.qsize() == 0:
                        if self.play_random and self.ctx.voice_client is not None:
                            async with self.ctx.typing():
                                audio = await YTDLSource.from_url(self.get_song_from_rnd_playlist(),
                                                                  loop=self.bot.loop,
                                                                  stream=True)
                                if audio:
                                    await self.queue.put((self.ctx, audio))
                                else:
                                    await self.ctx.invoke(self.bot.get_command('play_random'))
                                    await self.ctx.send('Birşeyler kırıldı.')
                        elif self.last_message:
                            await self.bot.change_presence(activity=self.bot.default_presence)
                            embed = self.last_message.embeds[0]
                            embed.description = 'Video bitti'
                            await self.last_message.edit(embed=embed)
                except NameError:
                    pass

                current = await self.queue.get()
                _ctx, audio = current
                self._ctx = _ctx
                self.ctx.voice_client.play(audio,
                                           after=lambda e: print('Player error: %s' % e) if e else self.toggle_next())
                self.source_start_tme = time.time()
                async with self.ctx.typing():
                    await self.send_player_embed(audio)
                await self.bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening,
                                                                         name=format(audio.title)))
                await self.play_next.wait()
        except AttributeError as error:
            print(error)
        except discord.errors.HTTPException as error:
            print(error)
        except asyncio.CancelledError as error:
            print(error)

    def dislike(self):
        if self.ctx.voice_client.source is None:
            return
        url = self.ctx.voice_client.source.url
        if url not in [url for url, s in self._random_playlist]:
            return
        conn = self.bot.get_pymysql_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('UPDATE playlist SET dislike = dislike + 1 WHERE url = "{}"'.format(url))
            conn.commit()
        finally:
            conn.close()
            return

    async def like(self):
        if self.ctx.voice_client.source is None:
            return
        url = self.ctx.voice_client.source.url
        if url not in [url for url, s in self._random_playlist]:
            return await self.ctx.send('Sadece şarkı listesindeki şarkılar beğenilebilir.')
        conn = self.bot.get_pymysql_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('UPDATE playlist SET like_count = like_count + 1 WHERE url = "{}"'.format(url))
            conn.commit()
        finally:
            conn.close()
            return
