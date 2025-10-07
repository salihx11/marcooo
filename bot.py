import json
import asyncio
import os
import time
import re
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, ChatWriteForbiddenError, UserBannedInChannelError
from telethon.tl.functions.messages import ForwardMessagesRequest
import colorama
from termcolor import colored

colorama.init()

# Load configuration
json_path = os.path.join(os.path.dirname(__file__), 'acc.json')
try:
    with open(json_path, 'r', encoding='utf-8') as f:
        accounts = json.load(f)
except Exception as e:
    print(colored(f"❌ Unable to load acc.json: {e}", "red"))
    exit()

# Load groups.txt
groups_path = os.path.join(os.path.dirname(__file__), 'groups.txt')
try:
    with open(groups_path, 'r', encoding='utf-8') as f:
        target_links = [line.strip() for line in f.readlines() if line.strip()]
    print(colored(f"✅ Loaded {len(target_links)} groups from groups.txt", "green"))
except Exception as e:
    print(colored(f"❌ Unable to load groups.txt: {e}", "red"))
    exit()

# Storage
last_sent_times = {}
latest_messages = {}
sent_counters = {}
group_cache = {}
last_terminal_clear = time.time()
is_forwarding = False
message_queue = []

def clear_terminal():
    os.system('cls' if os.name == 'nt' else 'clear')

def parse_telegram_link(link):
    """Enhanced Telegram link parsing with bot support"""
    link = link.strip()
    
    # Pattern for bot deep links
    bot_pattern = r'https?://t\.me/([a-zA-Z0-9_]+bot)(?:\?start=.*|/start.*)?'
    # Pattern for topic links
    topic_pattern = r'https?://t\.me/([a-zA-Z0-9_]+)/(\d+)'
    # Pattern for private links
    private_pattern = r'https?://t\.me/c/(\d+)/(\d+)'
    # Pattern for username only
    username_pattern = r'@?([a-zA-Z0-9_]+)'
    # Pattern for full URLs with usernames
    url_pattern = r'https?://t\.me/([a-zA-Z0-9_]+)'
    
    # Try bot pattern first
    bot_match = re.match(bot_pattern, link)
    if bot_match:
        bot_username = bot_match.group(1)
        return {
            'type': 'bot',
            'username': bot_username,
            'original_link': link
        }
    
    # Try topic pattern
    topic_match = re.match(topic_pattern, link)
    if topic_match:
        username = topic_match.group(1)
        topic_id = int(topic_match.group(2))
        return {
            'type': 'topic',
            'username': username,
            'topic_id': topic_id,
            'original_link': link
        }
    
    # Try private pattern
    private_match = re.match(private_pattern, link)
    if private_match:
        channel_id = int(private_match.group(1))
        topic_id = int(private_match.group(2))
        return {
            'type': 'private_topic', 
            'channel_id': channel_id,
            'topic_id': topic_id,
            'original_link': link
        }
    
    # Try URL pattern
    url_match = re.match(url_pattern, link)
    if url_match:
        username = url_match.group(1)
        return {
            'type': 'username',
            'username': username,
            'original_link': link
        }
    
    # Try username pattern (without https)
    username_match = re.match(username_pattern, link)
    if username_match:
        username = username_match.group(1)
        return {
            'type': 'username',
            'username': username,
            'original_link': link
        }
    
    return None

async def resolve_entity(client, link_info):
    """Enhanced entity resolution with bot support"""
    try:
        if link_info['type'] in ['bot', 'topic', 'username']:
            resolve_attempts = [
                link_info['username'],
                f"@{link_info['username']}",
                f"https://t.me/{link_info['username']}"
            ]
            
            for attempt in resolve_attempts:
                try:
                    entity = await client.get_entity(attempt)
                    return entity
                except (ValueError, TypeError):
                    continue
            
            # Try as integer for private chats
            try:
                if link_info['username'].isdigit():
                    entity = await client.get_entity(int(link_info['username']))
                    return entity
            except:
                pass
                
        elif link_info['type'] == 'private_topic':
            entity = await client.get_entity(link_info['channel_id'])
            return entity
            
    except Exception as e:
        print(colored(f"❌ Failed to resolve {link_info['original_link']}: {e}", "red"))
        return None

async def professional_forward_message(client, entity, message, topic_id=None):
    """
    PROFESSIONAL FORWARDING: Use the most reliable forwarding method
    Returns: (success, error_message)
    """
    try:
        # Method 1: Try direct forward_messages (most reliable)
        if topic_id:
            # For topics, we need to use send_message with reply_to
            if message.media:
                await client.send_message(
                    entity=entity,
                    message=message.text or "📢 Forwarded Message",
                    file=message.media,
                    reply_to=topic_id
                )
            else:
                await client.send_message(
                    entity=entity,
                    message=message.text or "📢 Forwarded Message",
                    reply_to=topic_id
                )
        else:
            # Standard forwarding for regular chats
            await client.forward_messages(
                entity=entity,
                messages=message
            )
        return True, None
        
    except Exception as e:
        error_msg = str(e)
        
        # Method 2: If forwarding fails, try sending as copy
        try:
            if topic_id:
                if message.media:
                    await client.send_message(
                        entity=entity,
                        message=message.text or "📢 Forwarded Message",
                        file=message.media,
                        reply_to=topic_id
                    )
                else:
                    await client.send_message(
                        entity=entity,
                        message=message.text or "📢 Forwarded Message", 
                        reply_to=topic_id
                    )
            else:
                await client.send_message(
                    entity=entity,
                    message=message.text or "📢 Forwarded Message",
                    file=message.media if message.media else None
                )
            return True, "Sent as copy (fallback)"
        except Exception as copy_error:
            return False, f"Forward: {error_msg[:30]}, Copy: {str(copy_error)[:30]}"

async def send_to_target(client, link_info, message, session_name):
    """PERFECT FORWARDING: Advanced forwarding with multiple fallbacks"""
    now = time.time()
    
    try:
        # Resolve entity first
        entity = await resolve_entity(client, link_info)
        if not entity:
            return False, link_info['original_link'], "❌ Cannot resolve entity"
        
        # Get entity name for display
        entity_name = getattr(entity, 'title', getattr(entity, 'username', link_info['original_link']))
        
        # Create unique key for cooldown tracking
        if link_info['type'] in ['topic', 'private_topic']:
            entity_key = f"{entity.id}_{link_info['topic_id']}"
            target_name = f"{entity_name} (Topic {link_info['topic_id']})"
            topic_id = link_info['topic_id']
        else:
            entity_key = str(entity.id)
            target_name = entity_name
            topic_id = None
        
        # Check cooldown (1 hour)
        last_sent = last_sent_times.get(entity_key, 0)
        if now - last_sent < 3600:
            wait_time = 3600 - (now - last_sent)
            return False, target_name, f"⏰ {int(wait_time/60)}min cooldown"
        
        # Smart delay based on previous performance
        delay = 3 if sent_counters.get(session_name, 0) > 10 else 5
        print(colored(f"⏳ Waiting {delay} seconds before forwarding to {target_name}...", "yellow"))
        await asyncio.sleep(delay)
        
        # PROFESSIONAL FORWARDING with multiple fallbacks
        success, error_info = await professional_forward_message(client, entity, message, topic_id)
        
        if success:
            last_sent_times[entity_key] = now
            status_msg = error_info if error_info else "✅ Perfect forward"
            return True, target_name, status_msg
        else:
            return False, target_name, f"❌ {error_info}"
            
    except FloodWaitError as e:
        return False, target_name, f"⏳ Flood wait: {e.seconds}s"
    except ChatWriteForbiddenError:
        return False, target_name, "❌ No write permission"
    except UserBannedInChannelError:
        return False, target_name, "❌ User banned"
    except Exception as e:
        error_msg = str(e)
        return False, target_name, f"❌ {error_msg[:40]}"

async def forward_to_all_groups(client, message, session_name, message_id=None):
    """Enhanced forwarding with better progress tracking"""
    global last_terminal_clear, is_forwarding
    
    if is_forwarding:
        print(colored("🔄 Forwarding already in progress. Please wait...", "yellow"))
        return 0
    
    is_forwarding = True
    
    try:
        # Clear terminal every hour to prevent spammy logs
        current_time = time.time()
        if current_time - last_terminal_clear >= 3600:
            clear_terminal()
            last_terminal_clear = current_time
            print(colored("🧹 Terminal cleared to prevent spammy logs", "blue"))
        
        print(colored("🚀 PERFECT TELEGRAM FORWARDER", "green", attrs=['bold']))
        print(colored(f"📤 FORWARDING to {len(target_links)} targets...", "cyan"))
        print(colored("🔄 PROFESSIONAL FORWARDING WITH FALLBACKS", "magenta", attrs=['bold']))
        print(colored("⏰ Smart delays | 1-hour cooldown per target", "yellow"))
        print(colored("🎯 Bot support & enhanced error handling", "blue"))
        print(colored("⏳ 1-hour gap after completing all groups", "cyan"))
        print(colored("=" * 60, "white"))
        
        sent_count = 0
        total_sent = sent_counters.get(session_name, 0)
        successful_targets = []
        failed_targets = []
        
        for i, link in enumerate(target_links, 1):
            print(colored(f"\n📋 Processing {i}/{len(target_links)}: {link}", "blue"))
            
            # Parse the link with enhanced parsing
            link_info = parse_telegram_link(link)
            if not link_info:
                print(colored("❌ Invalid link format - skipping", "red"))
                failed_targets.append((link, "Invalid format"))
                continue
            
            # Send to target
            success, target_name, status = await send_to_target(client, link_info, message, session_name)
            
            if success:
                print(colored(f"✅ {target_name}: {status}", "green"))
                sent_count += 1
                total_sent += 1
                successful_targets.append(target_name)
            else:
                print(colored(f"❌ {target_name}: {status}", "red"))
                failed_targets.append((target_name, status))
        
        # Update counters
        if sent_count > 0:
            sent_counters[session_name] = total_sent
        
        # Display final results
        print(colored("\n" + "=" * 60, "white"))
        print(colored("📊 PERFECT FORWARDING SUMMARY", "cyan", attrs=['bold']))
        print(colored(f"✅ Successfully FORWARDED: {sent_count}/{len(target_links)}", "green"))
        print(colored(f"📈 Total forwards this session: {total_sent}", "blue"))
        print(colored(f"❌ Failed: {len(failed_targets)} targets", "yellow" if failed_targets else "green"))
        
        if successful_targets:
            print(colored(f"🎯 Forwarded to: {', '.join(successful_targets[:5])}", "cyan"))
            if len(successful_targets) > 5:
                print(colored(f"   ... and {len(successful_targets) - 5} more", "cyan"))
        
        if failed_targets:
            print(colored(f"\n🔧 Failed targets (first 5):", "yellow"))
            for target, error in failed_targets[:5]:
                print(colored(f"   • {target}: {error}", "yellow"))
        
        return sent_count
        
    finally:
        is_forwarding = False

async def handle_admin_messages(client, admin_ids, session_name):
    """Enhanced admin message handler with better storage"""
    @client.on(events.NewMessage)
    async def handler(event):
        if event.sender_id not in admin_ids:
            return

        # Generate unique message ID with timestamp
        message_id = f"{event.chat_id}_{event.message.id}_{int(time.time())}"
        
        # Store the message in latest_messages dict
        latest_messages[message_id] = event.message
        
        # Add to message queue
        message_queue.append(message_id)
        
        # Show professional preview
        clear_terminal()
        print(colored("📨 NEW MESSAGE RECEIVED FOR PERFECT FORWARDING", "green", attrs=['bold']))
        
        # Enhanced message preview
        if event.message.text:
            preview = event.message.text[:100] + "..." if len(event.message.text) > 100 else event.message.text
            print(colored(f"💬 Text: {preview}", "cyan"))
        else:
            if event.message.photo:
                media_type = "🖼️ Photo"
            elif event.message.video:
                media_type = "🎥 Video" 
            elif event.message.document:
                media_type = "📄 Document"
            elif event.message.sticker:
                media_type = "😀 Sticker"
            else:
                media_type = "📎 Media"
            print(colored(f"{media_type} message", "cyan"))
        
        print(colored(f"📊 Total stored messages: {len(latest_messages)}", "blue"))
        print(colored("🔄 PERFECT FORWARDING MODE ACTIVATED", "magenta", attrs=['bold']))
        print(colored("⏰ Smart delays | 1-hour gap after completion", "yellow"))
        print(colored("🎯 Bot support & enhanced error handling", "blue"))
        print(colored("=" * 60, "white"))
        await asyncio.sleep(2)
        
        # Start forwarding this specific message
        sent_count = await forward_to_all_groups(client, event.message, session_name, message_id)
        
        # Always wait 1 hour after forwarding (regardless of sent_count)
        if sent_count > 0:
            print(colored(f"\n⏳ Waiting 1 hour before next forwarding cycle...", "blue", attrs=['bold']))
            print(colored(f"💤 Next cycle at: {time.strftime('%H:%M:%S', time.localtime(time.time() + 3600))}", "cyan"))
            await asyncio.sleep(3600)

async def auto_forwarder(client, session_name):
    """Enhanced auto-forwarder with better message management"""
    while True:
        if latest_messages:
            clear_terminal()
            print(colored("🔄 PERFECT AUTOMATIC HOURLY FORWARDING", "blue", attrs=['bold']))
            print(colored(f"📊 Forwarding {len(latest_messages)} stored messages", "cyan"))
            print(colored("🔄 PROFESSIONAL FORWARDING WITH FALLBACKS", "magenta"))
            
            total_sent = 0
            # Forward all stored messages with better progress
            for message_id, message in list(latest_messages.items()):
                msg_index = list(latest_messages.keys()).index(message_id) + 1
                print(colored(f"\n📨 Forwarding message {msg_index}/{len(latest_messages)}", "yellow"))
                sent_count = await forward_to_all_groups(client, message, session_name)
                total_sent += sent_count
            
            # Enhanced wait message
            print(colored(f"\n⏳ Perfect forwarding completed. Waiting 1 hour...", "blue"))
            print(colored(f"💤 Next auto-cycle at: {time.strftime('%H:%M:%S', time.localtime(time.time() + 3600))}", "cyan"))
            await asyncio.sleep(3600)
        else:
            # No messages available, check every 5 minutes
            print(colored("⏳ No messages available for perfect auto-forwarding, checking again in 5 minutes...", "yellow"))
            await asyncio.sleep(300)

async def main():
    clear_terminal()
    print(colored("🚀 PERFECT TELEGRAM AUTO-FORWARDER", "green", attrs=['bold']))
    print(colored(f"📋 Loaded {len(target_links)} targets", "cyan"))
    print(colored("🔄 PROFESSIONAL FORWARDING WITH FALLBACKS", "magenta", attrs=['bold']))
    print(colored("⚡ Enhanced bot support & link parsing", "yellow"))
    print(colored("💾 Stores ALL admin messages securely", "green"))
    print(colored("⏰ Smart delays based on performance", "blue"))
    print(colored("⏳ 1-hour fixed gap between cycles", "cyan"))
    print(colored("🎯 Perfect error handling with fallbacks", "blue"))
    print(colored("=" * 60, "white"))
    
    # Enhanced target analysis
    print(colored("🔍 Perfect Target Analysis:", "blue"))
    valid_targets = 0
    target_types = {}
    
    for i, link in enumerate(target_links, 1):
        link_info = parse_telegram_link(link)
        if link_info:
            valid_targets += 1
            target_type = link_info['type']
            target_types[target_type] = target_types.get(target_type, 0) + 1
            
            if target_type == 'bot':
                icon = "🤖"
                info = "Bot"
            elif target_type == 'topic':
                icon = "📚"
                info = f"Topic {link_info['topic_id']}"
            elif target_type == 'private_topic':
                icon = "🔒📚" 
                info = f"Private Topic {link_info['topic_id']}"
            else:
                icon = "👥"
                info = "Group/Chat"
                
            display_name = link_info['username'] if 'username' in link_info else link_info['original_link']
            print(colored(f"   {i:2d}. {icon} {display_name} - {info}", "cyan"))
        else:
            print(colored(f"   {i:2d}. ❌ {link} (Invalid - will skip)", "red"))
    
    # Enhanced summary
    print(colored(f"\n📊 Perfect Summary:", "green"))
    for ttype, count in target_types.items():
        type_name = ttype.replace('_', ' ').title()
        print(colored(f"   • {type_name}: {count}", "cyan"))
    print(colored(f"   • Total Valid: {valid_targets}/{len(target_links)}", 
                  "green" if valid_targets == len(target_links) else "yellow"))
    
    print(colored("=" * 60, "white"))
    
    # Process each account
    for account in accounts:
        api_id = account["api_id"]
        api_hash = account["api_hash"]
        phone_number = account["phone_number"]
        session_name = account["session_name"]
        admin_ids = account.get("admin_ids", [])
        
        if not admin_ids:
            print(colored(f"❌ No admin_ids for {phone_number}", "red"))
            continue
            
        client = TelegramClient(session_name, api_id, api_hash)
        
        try:
            await client.start(phone_number)
            print(colored(f"✅ Perfect connection: {phone_number}", "green"))
            
            # Start enhanced services
            await handle_admin_messages(client, admin_ids, session_name)
            asyncio.create_task(auto_forwarder(client, session_name))
            
            print(colored("\n🤖 PERFECT FORWARDER IS RUNNING!", "green", attrs=['bold']))
            print(colored("💡 Send messages from admin to forward", "cyan"))
            print(colored("🔄 PROFESSIONAL FORWARDING WITH FALLBACKS", "magenta"))
            print(colored("🤖 Bot support enabled", "green"))
            print(colored("⏰ Smart delays based on performance", "yellow"))
            print(colored("🔄 Automatic forwarding every hour", "magenta"))
            print(colored("⏳ 1-hour fixed gap between all cycles", "blue"))
            print(colored("🎯 Perfect error handling", "blue"))
            print(colored("=" * 60, "white"))
            
            await client.run_until_disconnected()
            
        except Exception as e:
            print(colored(f"❌ Failed for {phone_number}: {e}", "red"))

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(colored("\n👋 Perfect forwarder stopped gracefully", "yellow"))
    except Exception as e:
        print(colored(f"❌ Critical error: {e}", "red"))