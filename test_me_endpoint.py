"""Test the /me endpoint to see what the backend returns."""
import requests
import json

print("=" * 70)
print("🧪 TESTING /me ENDPOINT")
print("=" * 70)

# You need to get your actual JWT token from the frontend
print("\n📝 INSTRUCTIONS:")
print("1. Open your browser DevTools (F12)")
print("2. Go to Application/Storage → Local Storage or Session Storage")
print("3. Look for your Clerk token (might be in __session or similar)")
print("4. OR: Add this to your frontend code temporarily:")
print("   const token = await getToken();")
print("   console.log('TOKEN:', token);")
print("\n5. Copy the token and paste it here:")
print("\n" + "=" * 70)

token = input("Enter your JWT token: ").strip()

if not token:
    print("❌ No token provided!")
    exit(1)

print("\n" + "=" * 70)
print("🔄 CALLING BACKEND /me ENDPOINT...")
print("=" * 70)

try:
    response = requests.get(
        "http://localhost:8000/me",
        headers={
            "Authorization": f"Bearer {token}"
        }
    )
    
    print(f"\n📊 Response Status: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print("\n✅ SUCCESS! Backend Response:")
        print(json.dumps(data, indent=2))
        
        if "data" in data:
            user_data = data["data"]
            role = user_data.get("role", "NO ROLE FOUND")
            
            print("\n" + "=" * 70)
            print("🎯 ROLE CHECK:")
            print("=" * 70)
            print(f"  Backend returns role: '{role}'")
            
            if role == "TEACHER":
                print("  ✅ Role is TEACHER - Backend is correct!")
                print("\n  🔍 This means the problem is in the FRONTEND!")
                print("  👉 Your frontend needs to check: user.role === 'TEACHER'")
            elif role == "admin":
                print("  ⚠️  Role is still 'admin' - Backend not updated yet")
                print("  👉 Need to restart backend server")
            else:
                print(f"  ❌ Unexpected role: '{role}'")
    else:
        print(f"\n❌ ERROR: {response.status_code}")
        print(response.text)
        
        if response.status_code == 401:
            print("\n💡 Token might be expired or invalid")
            print("   Try logging out and logging back in")
        
except requests.exceptions.ConnectionError:
    print("\n❌ Cannot connect to backend!")
    print("   Make sure backend is running on http://localhost:8000")
except Exception as e:
    print(f"\n❌ Error: {e}")
